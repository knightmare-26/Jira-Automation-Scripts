/**
 * Main function to run weekly. Orchestrates reading sheets, querying Jira,
 * identifying discrepancies, and updating the validation report.
 */
function weeklyValidationAndNotification() {
  const properties = PropertiesService.getScriptProperties();
  const SCRIPT_LOG_SHEET_NAME = properties.getProperty('SCRIPT_LOG_SHEET_NAME');
  const GOOGLE_SHEET_ID = properties.getProperty('GOOGLE_SHEET_ID');

  const spreadsheet = SpreadsheetApp.openById(GOOGLE_SHEET_ID);
  const logSheet = getOrCreateSheet(spreadsheet, SCRIPT_LOG_SHEET_NAME, ['Timestamp', 'Type', 'Message']);

  log('Starting weekly validation script.', 'INFO', logSheet);

  try {
    // 1. Read Google Sheet
    const timelineData = readDeliveryTimelineSheet(spreadsheet, logSheet);
    if (!timelineData) {
      log('Failed to read delivery timeline. Aborting.', 'ERROR', logSheet);
      return;
    }
    const trainMilestoneLookup = buildTrainMilestoneLookup(timelineData, logSheet);
    const allTrains = Object.keys(trainMilestoneLookup);
    log(`Found ${allTrains.length} trains in the sheet.`, 'INFO', logSheet);

    if (allTrains.length === 0) {
      log('No trains found in the sheet. Nothing to validate. Exiting.', 'INFO', logSheet);
      return;
    }

    // 2. Query Jira
    const jiraIssues = queryJiraForTrains(allTrains, logSheet);
    log(`Found ${jiraIssues.length} Jira issues matching trains.`, 'INFO', logSheet);

    // 3. Compare Dates & Identify Discrepancies
    const discrepancies = identifyDiscrepancies(jiraIssues, trainMilestoneLookup, logSheet);
    log(`Identified ${discrepancies.length} discrepancies.`, 'INFO', logSheet);

    // 4. Update Validation Report Sheet (de-duplication & state management)
    updateValidationReportSheet(spreadsheet, discrepancies, logSheet); // Now this only updates the sheet

    // 5. Get pending, unnotified discrepancies for email
    const discrepanciesToNotify = getPendingUnnotifiedDiscrepancies(spreadsheet, logSheet);

    if (discrepanciesToNotify.length > 0) {
      sendApprovalEmail(discrepanciesToNotify, spreadsheet, logSheet);
      markDiscrepanciesAsNotified(discrepanciesToNotify, spreadsheet, logSheet);
      log(`Sent approval email for ${discrepanciesToNotify.length} new pending discrepancies.`, 'INFO', logSheet);
    } else {
      log('No new pending discrepancies to send for approval.', 'INFO', logSheet);
    }

  } catch (e) {
    log(`An unexpected error occurred: ${e.message} Stack: ${e.stack}`, 'FATAL', logSheet);
  }

  log('Weekly validation script finished.', 'INFO', logSheet);
}

/**
 * Reads the "Delivery Timeline" sheet and returns its data as an array of objects.
 * Handles dynamic column mapping.
 * @param {GoogleAppsScript.Spreadsheet.Spreadsheet} spreadsheet The active Google Spreadsheet.
 * @param {GoogleAppsScript.Spreadsheet.Sheet} logSheet The sheet for logging.
 * @returns {Array<Object>|null} An array of objects, each representing a row, or null on error.
 */
function readDeliveryTimelineSheet(spreadsheet, logSheet) {
  const properties = PropertiesService.getScriptProperties();
  const DELIVERY_TIMELINE_SHEET_NAME = properties.getProperty('DELIVERY_TIMELINE_SHEET_NAME');

  try {
    const sheet = spreadsheet.getSheetByName(DELIVERY_TIMELINE_SHEET_NAME);
    if (!sheet) {
      log(`Sheet '${DELIVERY_TIMELINE_SHEET_NAME}' not found.`, 'ERROR', logSheet);
      return null;
    }

    const dataRange = sheet.getDataRange();
    const values = dataRange.getDisplayValues(); // getDisplayValues to match displayed formatting

    if (values.length < 2) {
      log(`Sheet '${DELIVERY_TIMELINE_SHEET_NAME}' is empty or has only headers.`, 'WARNING', logSheet);
      return [];
    }

    const headers = values[0];
    const rawData = values.slice(1);
    const timelineData = [];

    // Map common column names to internal keys for robustness against varying column names
    const columnMap = {
      'train identifier': 'train',
      'train name': 'train',
      'milestone name': 'milestone',
      'milestone': 'milestone',
      'start date': 'startDate',
      'duration (days)': 'duration',
      'end date': 'endDate',
      'quarter': 'quarter'
    };

    const mappedHeaders = headers.map(header => {
      const lowerCaseHeader = header.toLowerCase().trim();
      return columnMap[lowerCaseHeader] || null; // Return null for unmapped headers
    });

    rawData.forEach(row => {
      const rowObject = {};
      mappedHeaders.forEach((mappedHeader, index) => {
        if (mappedHeader) { // Only add if header was mapped
          rowObject[mappedHeader] = row[index];
        }
      });
      // Ensure essential fields exist
      if (rowObject.train && rowObject.milestone && rowObject.endDate) {
        timelineData.push(rowObject);
      } else {
          log(`Skipping row due to missing essential data: ${JSON.stringify(row)}`, 'WARNING', logSheet);
      }
    });

    return timelineData;

  } catch (e) {
    log(`Error reading sheet '${DELIVERY_TIMELINE_SHEET_NAME}': ${e.message}`, 'ERROR', logSheet);
    return null;
  }
}

/**
 * Builds a lookup object for milestone dates per train from the raw timeline data.
 * @param {Array<Object>} timelineData The parsed data from the delivery timeline sheet.
 * @param {GoogleAppsScript.Spreadsheet.Sheet} logSheet The sheet for logging.
 * @returns {Object} A map like { "TrainName": { "Branch Cut": "YYYY-MM-DD", "Regression Signoff": "YYYY-MM-DD" }, ... }
 */
function buildTrainMilestoneLookup(timelineData, logSheet) {
  const lookup = {};

  timelineData.forEach(row => {
    const train = row.train;
    const milestone = row.milestone;
    const endDate = row.endDate; // This will be a string from getDisplayValues

    if (!train || !milestone || !endDate) {
      log(`Skipping row in lookup build due to missing data: ${JSON.stringify(row)}`, 'WARNING', logSheet);
      return;
    }

    if (!lookup[train]) {
      lookup[train] = {};
    }

    // Standardize milestone names for lookup
    if (milestone.toLowerCase().includes('branch cut')) {
      lookup[train]['Branch Cut'] = endDate;
    } else if (milestone.toLowerCase().includes('regression signoff')) {
      lookup[train]['Regression Signoff'] = endDate;
    }
  });
  return lookup;
}

/**
 * Queries Jira for Epic and Feature issues whose Train field matches any of the given trains.
 * @param {Array<string>} allTrains An array of all unique train identifiers.
 * @param {GoogleAppsScript.Spreadsheet.Sheet} logSheet The sheet for logging.
 * @returns {Array<Object>} An array of Jira issue objects.
 */
function queryJiraForTrains(allTrains, logSheet) {
  const properties = PropertiesService.getScriptProperties();
  const JIRA_TRAIN_FIELD_ID = properties.getProperty('JIRA_TRAIN_FIELD_ID');
  const JIRA_DEV_COMPLETION_DATE_FIELD_ID = properties.getProperty('JIRA_DEV_COMPLETION_DATE_FIELD_ID');
  const JIRA_QA_SIGNOFF_DATE_FIELD_ID = properties.getProperty('JIRA_QA_SIGNOFF_DATE_FIELD_ID');

  if (allTrains.length === 0) {
    return [];
  }

  // Construct JQL to search for issues in specified trains
  // Using 'in' clause for the custom field
  const trainJQLList = allTrains.map(train => `'${train}'`).join(', ');
  const jql = `issuetype in ("Epic", "Feature") AND "${JIRA_TRAIN_FIELD_ID}" in (${trainJQLList})`;

  // Define fields to retrieve, including custom fields for dates and the train identifier
  const fields = [
    'summary', // Standard field
    'issuetype', // Standard field
    JIRA_TRAIN_FIELD_ID,
    JIRA_DEV_COMPLETION_DATE_FIELD_ID,
    JIRA_QA_SIGNOFF_DATE_FIELD_ID
  ].join(',');

  const endpoint = `/rest/api/3/search?jql=${encodeURIComponent(jql)}&fields=${encodeURIComponent(fields)}&maxResults=1000`; // Adjust maxResults as needed
  const response = makeJiraApiCall('GET', endpoint, null, logSheet);

  if (!response || !response.issues) {
    log('Jira query returned no issues or an error.', 'WARNING', logSheet);
    return [];
  }

  // Map raw Jira response to a more usable format
  const jiraIssues = response.issues.map(issue => {
    const fields = issue.fields;
    return {
      key: issue.key,
      issueType: fields.issuetype.name,
      train: fields[JIRA_TRAIN_FIELD_ID], // The value of the custom field
      devCompletionDate: fields[JIRA_DEV_COMPLETION_DATE_FIELD_ID], // ISO date string or null
      qaSignoffDate: fields[JIRA_QA_SIGNOFF_DATE_FIELD_ID] // ISO date string or null
    };
  });

  return jiraIssues;
}

/**
 * Identifies discrepancies between Jira issue dates and Google Sheet milestone dates.
 * @param {Array<Object>} jiraIssues Fetched Jira issue data.
 * @param {Object} trainMilestoneLookup Lookup for authoritative dates from Google Sheet.
 * @param {GoogleAppsScript.Spreadsheet.Sheet} logSheet The sheet for logging.
 * @returns {Array<Object>} An array of discrepancy objects.
 */
function identifyDiscrepancies(jiraIssues, trainMilestoneLookup, logSheet) {
  const discrepancies = [];

  jiraIssues.forEach(issue => {
    const train = issue.train;
    const sheetDates = trainMilestoneLookup[train];

    if (!sheetDates) {
      log(`No sheet milestone dates found for Train '${train}' (Jira Issue: ${issue.key}). Skipping.`, 'WARNING', logSheet);
      return;
    }

    const sheetBranchCutDate = sheetDates['Branch Cut'];
    const sheetRegressionSignoffDate = sheetDates['Regression Signoff'];

    // Compare Dev Completion Date (Branch Cut)
    const jiraDevDate = issue.devCompletionDate ? Utilities.formatDate(new Date(issue.devCompletionDate), Session.getScriptTimeZone(), 'yyyy-MM-dd') : null;
    const expectedDevDate = sheetBranchCutDate ? Utilities.formatDate(new Date(sheetBranchCutDate), Session.getScriptTimeZone(), 'yyyy-MM-dd') : null;

    if (!jiraDevDate && expectedDevDate) {
      discrepancies.push({
        issueKey: issue.key,
        issueType: issue.issueType,
        train: train,
        fieldName: 'Dev Completion Date',
        currentJiraValue: 'MISSING',
        proposedSheetValue: expectedDevDate,
        status: 'Pending',
        notified: false,
        proposedAt: new Date()
      });
    } else if (jiraDevDate !== expectedDevDate) {
      discrepancies.push({
        issueKey: issue.key,
        issueType: issue.issueType,
        train: train,
        fieldName: 'Dev Completion Date',
        currentJiraValue: jiraDevDate,
        proposedSheetValue: expectedDevDate,
        status: 'Pending',
        notified: false,
        proposedAt: new Date()
      });
    }

    // Compare QA Sign-off Date (Regression Signoff)
    const jiraQADate = issue.qaSignoffDate ? Utilities.formatDate(new Date(issue.qaSignoffDate), Session.getScriptTimeZone(), 'yyyy-MM-dd') : null;
    const expectedQADate = sheetRegressionSignoffDate ? Utilities.formatDate(new Date(sheetRegressionSignoffDate), Session.getScriptTimeZone(), 'yyyy-MM-dd') : null;

    if (!jiraQADate && expectedQADate) {
      discrepancies.push({
        issueKey: issue.key,
        issueType: issue.issueType,
        train: train,
        fieldName: 'QA Sign-off Date',
        currentJiraValue: 'MISSING',
        proposedSheetValue: expectedQADate,
        status: 'Pending',
        notified: false,
        proposedAt: new Date()
      });
    } else if (jiraQADate !== expectedQADate) {
      discrepancies.push({
        issueKey: issue.key,
        issueType: issue.issueType,
        train: train,
        fieldName: 'QA Sign-off Date',
        currentJiraValue: jiraQADate,
        proposedSheetValue: expectedQADate,
        status: 'Pending',
        notified: false,
        proposedAt: new Date()
      });
    }
  });

  return discrepancies;
}

/**
 * Updates the "Validation Report" sheet with new discrepancies, handles de-duplication,
 * and manages status changes.
 * @param {GoogleAppsScript.Spreadsheet.Spreadsheet} spreadsheet The active Google Spreadsheet.
 * @param {Array<Object>} newDiscrepancies The newly identified discrepancies.
 * @param {GoogleAppsScript.Spreadsheet.Sheet} logSheet The sheet for logging.
 */
function updateValidationReportSheet(spreadsheet, newDiscrepancies, logSheet) {
  const properties = PropertiesService.getScriptProperties();
  const VALIDATION_REPORT_SHEET_NAME = properties.getProperty('VALIDATION_REPORT_SHEET_NAME');

  const headers = [
    'Jira Issue Key', 'Issue Type', 'Train', 'Field Name', 'Current Jira Value',
    'Proposed Value (from Sheet)', 'Status', 'Notified', 'Proposed At',
    'Approved By', 'Approved At', 'Applied By', 'Applied At', 'Approve?' // 'Approve?' is for user interaction
  ];
  const reportSheet = getOrCreateSheet(spreadsheet, VALIDATION_REPORT_SHEET_NAME, headers);

  const existingData = reportSheet.getDataRange().getValues();
  // Assuming the first row is headers, slice it off
  const existingReportRows = existingData.length > 1 ? existingData.slice(1) : [];

  const currentReportState = {}; // Map unique discrepancy key to its original row object and index
  existingReportRows.forEach((row, index) => {
    // A robust unique key for a pending discrepancy
    const key = `${row[0]}~${row[3]}~${row[5]}`; // IssueKey~FieldName~ProposedValue
    currentReportState[key] = { row: row, sheetIndex: index + 2 }; // +2 for header row and 0-based array index
  });

  const rowsToAppend = [];
  const rowsToUpdate = []; // [{ range, values }]

  // Iterate over newly found discrepancies
  newDiscrepancies.forEach(newDisc => {
    const uniqueKey = `${newDisc.issueKey}~${newDisc.fieldName}~${newDisc.proposedSheetValue}`;
    const existingEntry = currentReportState[uniqueKey];

    if (existingEntry) {
      // Discrepancy already exists. Check if its status needs update (e.g., from Resolved back to Pending)
      const existingStatus = existingEntry.row[6]; // Status column
      if (existingStatus !== 'Pending' && existingStatus !== 'Applied') {
        // It was resolved or rejected, but it's back. Re-open it.
        existingEntry.row[6] = 'Pending';
        existingEntry.row[7] = false; // Notified = false (needs new notification)
        existingEntry.row[8] = Utilities.formatDate(new Date(), Session.getScriptTimeZone(), 'yyyy-MM-dd HH:mm:ss'); // Update Proposed At
        existingEntry.row[9] = ''; // Clear approval info
        existingEntry.row[10] = '';
        existingEntry.row[11] = ''; // Clear applied info
        existingEntry.row[12] = '';
        existingEntry.row[13] = false; // Clear approve checkbox
        rowsToUpdate.push({ range: reportSheet.getRange(existingEntry.sheetIndex, 1, 1, headers.length), values: [existingEntry.row] });
        log(`Re-opened discrepancy for ${newDisc.issueKey} - ${newDisc.fieldName}.`, 'INFO', logSheet);
      }
      delete currentReportState[uniqueKey]; // Remove from map as it's handled
    } else {
      // This is a genuinely new discrepancy
      const row = [
        newDisc.issueKey,
        newDisc.issueType,
        newDisc.train,
        newDisc.fieldName,
        newDisc.currentJiraValue,
        newDisc.proposedSheetValue,
        'Pending', // Initial status
        false,     // Not yet notified
        Utilities.formatDate(newDisc.proposedAt, Session.getScriptTimeZone(), 'yyyy-MM-dd HH:mm:ss'),
        '', '', '', '', // Approval and Applied info
        false      // Approve? checkbox
      ];
      rowsToAppend.push(row);
    }
  });

  // Mark existing 'Pending' discrepancies that are *not* in `newDiscrepancies` as 'Resolved Automatically'
  for (const key in currentReportState) {
    const entry = currentReportState[key];
    if (entry.row[6] === 'Pending') { // If it was pending and is no longer found
      entry.row[6] = 'Resolved Automatically';
      entry.row[7] = false; // Reset notified
      entry.row[9] = ''; // Clear approval info
      entry.row[10] = '';
      entry.row[11] = ''; // Clear applied info
      entry.row[12] = '';
      entry.row[13] = false; // Clear approve checkbox
      rowsToUpdate.push({ range: reportSheet.getRange(entry.sheetIndex, 1, 1, headers.length), values: [entry.row] });
      log(`Discrepancy for ${entry.row[0]} - ${entry.row[3]} (proposed: ${entry.row[5]}) is now Resolved Automatically.`, 'INFO', logSheet);
    }
  }

  // Apply all collected updates
  if (rowsToAppend.length > 0) {
    reportSheet.getRange(reportSheet.getLastRow() + 1, 1, rowsToAppend.length, headers.length).setValues(rowsToAppend);
    log(`Added ${rowsToAppend.length} new discrepancies to '${VALIDATION_REPORT_SHEET_NAME}'.`, 'INFO', logSheet);
  }
  rowsToUpdate.forEach(update => {
    update.range.setValues(update.values);
  });
  if (rowsToUpdate.length > 0) {
      log(`Updated ${rowsToUpdate.length} existing discrepancies in '${VALIDATION_REPORT_SHEET_NAME}'.`, 'INFO', logSheet);
  }
}

/**
 * Reads the "Validation Report" sheet and returns a list of discrepancies that are
 * 'Pending' and have 'Notified' status as false.
 * @param {GoogleAppsScript.Spreadsheet.Spreadsheet} spreadsheet The active Google Spreadsheet.
 * @param {GoogleAppsScript.Spreadsheet.Sheet} logSheet The sheet for logging.
 * @returns {Array<Object>} An array of discrepancy objects that need to be notified.
 */
function getPendingUnnotifiedDiscrepancies(spreadsheet, logSheet) {
  const properties = PropertiesService.getScriptProperties();
  const VALIDATION_REPORT_SHEET_NAME = properties.getProperty('VALIDATION_REPORT_SHEET_NAME');
  const reportSheet = spreadsheet.getSheetByName(VALIDATION_REPORT_SHEET_NAME);

  if (!reportSheet) {
    log(`Validation Report Sheet '${VALIDATION_REPORT_SHEET_NAME}' not found. Cannot get pending discrepancies.`, 'ERROR', logSheet);
    return [];
  }

  const dataRange = reportSheet.getDataRange();
  const values = dataRange.getValues();

  if (values.length < 2) { // No data or only headers
    return [];
  }

  const headers = values[0];
  const pendingUnnotified = [];

  // Find column indices
  const statusCol = headers.indexOf('Status');
  const notifiedCol = headers.indexOf('Notified');

  if (statusCol === -1 || notifiedCol === -1) {
    log('Required columns (Status, Notified) not found in Validation Report sheet headers.', 'ERROR', logSheet);
    return [];
  }

  values.slice(1).forEach((row, index) => {
    if (row[statusCol] === 'Pending' && row[notifiedCol] === false) {
      pendingUnnotified.push({
        issueKey: row[headers.indexOf('Jira Issue Key')],
        issueType: row[headers.indexOf('Issue Type')],
        train: row[headers.indexOf('Train')],
        fieldName: row[headers.indexOf('Field Name')],
        currentJiraValue: row[headers.indexOf('Current Jira Value')],
        proposedSheetValue: row[headers.indexOf('Proposed Value (from Sheet)')],
        sheetRowIndex: index + 2 // +1 for 0-based slice, +1 for header row
      });
    }
  });
  return pendingUnnotified;
}

/**
 * Sends an email summary of discrepancies requiring approval.
 * @param {Array<Object>} discrepanciesToNotify An array of discrepancy objects to include in the email.
 * @param {GoogleAppsScript.Spreadsheet.Spreadsheet} spreadsheet The active Google Spreadsheet.
 * @param {GoogleAppsScript.Spreadsheet.Sheet} logSheet The sheet for logging.
 */
function sendApprovalEmail(discrepanciesToNotify, spreadsheet, logSheet) {
  const properties = PropertiesService.getScriptProperties();
  const APPROVAL_EMAIL_RECIPIENT = properties.getProperty('APPROVAL_EMAIL_RECIPIENT');
  const GOOGLE_SHEET_ID = properties.getProperty('GOOGLE_SHEET_ID');
  const VALIDATION_REPORT_SHEET_NAME = properties.getProperty('VALIDATION_REPORT_SHEET_NAME');

  if (!APPROVAL_EMAIL_RECIPIENT) {
    log('APPROVAL_EMAIL_RECIPIENT is not configured in Script Properties. Email not sent.', 'WARNING', logSheet);
    return;
  }
  if (discrepanciesToNotify.length === 0) {
    log('No discrepancies to notify, skipping email.', 'INFO', logSheet);
    return;
  }

  let emailBody = `<html><body>
    <p>Hello,</p>
    <p>The weekly Jira-Google Sheet validation script has identified the following discrepancies requiring your approval:</p>
    <table border="1" style="border-collapse: collapse; width: 100%;">
      <tr style="background-color: #f2f2f2;">
        <th>Jira Issue Key</th>
        <th>Issue Type</th>
        <th>Train</th>
        <th>Field to Update</th>
        <th>Current Jira Value</th>
        <th>Proposed Value (from Sheet)</th>
      </tr>`;

  discrepanciesToNotify.forEach(disc => {
    emailBody += `
      <tr>
        <td>${disc.issueKey}</td>
        <td>${disc.issueType}</td>
        <td>${disc.train}</td>
        <td>${disc.fieldName}</td>
        <td>${disc.currentJiraValue}</td>
        <td>${disc.proposedSheetValue}</td>
      </tr>`;
  });

  const validationReportUrl = `https://docs.google.com/spreadsheets/d/${GOOGLE_SHEET_ID}/edit#gid=${spreadsheet.getSheetByName(VALIDATION_REPORT_SHEET_NAME).getSheetId()}`;

  emailBody += `
    </table>
    <p>Please review these discrepancies in the <a href="${validationReportUrl}">Validation Report Sheet</a>.</p>
    <p>To approve an update, check the "Approve?" box in the corresponding row of the Validation Report sheet. Once approved, the script will apply the updates to Jira.</p>
    <p>Thank you.</p>
  </body></html>`;

  try {
    GmailApp.sendEmail(APPROVAL_EMAIL_RECIPIENT, 'Jira-Google Sheet Milestone Date Discrepancies Approval Request', '', {
      htmlBody: emailBody,
      name: 'Automated Jira Validator' // Sender name
    });
    log(`Approval email sent to ${APPROVAL_EMAIL_RECIPIENT} for ${discrepanciesToNotify.length} discrepancies.`, 'INFO', logSheet);
  } catch (e) {
    log(`Failed to send approval email: ${e.message}`, 'ERROR', logSheet);
  }
}

/**
 * Marks the specified discrepancies as 'Notified' in the Validation Report sheet.
 * @param {Array<Object>} discrepanciesToNotify An array of discrepancy objects that were just notified.
 * @param {GoogleAppsScript.Spreadsheet.Spreadsheet} spreadsheet The active Google Spreadsheet.
 * @param {GoogleAppsScript.Spreadsheet.Sheet} logSheet The sheet for logging.
 */
function markDiscrepanciesAsNotified(discrepanciesToNotify, spreadsheet, logSheet) {
  const properties = PropertiesService.getScriptProperties();
  const VALIDATION_REPORT_SHEET_NAME = properties.getProperty('VALIDATION_REPORT_SHEET_NAME');
  const reportSheet = spreadsheet.getSheetByName(VALIDATION_REPORT_SHEET_NAME);

  if (!reportSheet) {
    log(`Validation Report Sheet '${VALIDATION_REPORT_SHEET_NAME}' not found. Cannot mark discrepancies as notified.`, 'ERROR', logSheet);
    return;
  }

  const headers = reportSheet.getRange(1, 1, 1, reportSheet.getLastColumn()).getValues()[0];
  const notifiedCol = headers.indexOf('Notified') + 1; // +1 for 1-based index

  if (notifiedCol === 0) { // If 'Notified' header not found
    log('Could not find "Notified" column in Validation Report sheet. Cannot mark discrepancies.', 'ERROR', logSheet);
    return;
  }

  // To update a specific cell in a specific row
  discrepanciesToNotify.forEach(disc => {
    reportSheet.getRange(disc.sheetRowIndex, notifiedCol).setValue(true);
  });

  log(`Marked ${discrepanciesToNotify.length} discrepancies as notified in Validation Report.`, 'INFO', logSheet);
}


/**
 * Makes an authenticated API call to Jira.
 * @param {string} method HTTP method (GET, POST, PUT).
 * @param {string} endpoint Jira API endpoint (e.g., '/rest/api/3/search').
 * @param {Object|null} payload Request body for POST/PUT.
 * @param {GoogleAppsScript.Spreadsheet.Sheet} logSheet The sheet for logging.
 * @returns {Object|null} Parsed JSON response from Jira, or null on error.
 */
function makeJiraApiCall(method, endpoint, payload, logSheet) {
  const properties = PropertiesService.getScriptProperties();
  const JIRA_BASE_URL = properties.getProperty('JIRA_BASE_URL');

  const url = JIRA_BASE_URL + endpoint;
  const authHeader = getJiraAuthHeader();

  const options = {
    method: method,
    headers: {
      'Authorization': authHeader,
      'Content-Type': 'application/json',
      'Accept': 'application/json'
    },
    muteHttpExceptions: true // Don't throw exceptions for HTTP errors, allow inspection of response
  };

  if (payload) {
    options.payload = JSON.stringify(payload);
  }

  try {
    const response = UrlFetchApp.fetch(url, options);
    const responseCode = response.getResponseCode();
    const responseBody = response.getContentText();

    if (responseCode >= 200 && responseCode < 300) {
      if (responseBody) { // Some successful responses might have no body (e.g., 204 No Content)
        return JSON.parse(responseBody);
      }
      return {}; // Return empty object for successful responses with no body
    } else {
      log(`Jira API call failed: ${method} ${endpoint}. Code: ${responseCode}. Response: ${responseBody}`, 'ERROR', logSheet);
      return null;
    }
  } catch (e) {
    log(`Exception during Jira API call: ${method} ${endpoint}. Error: ${e.message}`, 'FATAL', logSheet);
    return null;
  }
}

/**
 * Generates the Basic Authorization header for Jira API calls.
 * @returns {string} The Authorization header value.
 */
function getJiraAuthHeader() {
  const properties = PropertiesService.getScriptProperties();
  const JIRA_EMAIL = properties.getProperty('JIRA_EMAIL');
  const JIRA_API_TOKEN = properties.getProperty('JIRA_API_TOKEN');
  const credentials = Utilities.base64Encode(`${JIRA_EMAIL}:${JIRA_API_TOKEN}`);
  return `Basic ${credentials}`;
}

/**
 * Appends a log message to the specified log sheet.
 * @param {string} message The message to log.
 * @param {string} type The type of log (INFO, WARNING, ERROR, FATAL).
 * @param {GoogleAppsScript.Spreadsheet.Sheet} logSheet The sheet for logging.
 */
function log(message, type = 'INFO', logSheet) {
  const timestamp = Utilities.formatDate(new Date(), Session.getScriptTimeZone(), 'yyyy-MM-dd HH:mm:ss');
  logSheet.appendRow([timestamp, type, message]);
  // Also log to console for easier debugging during development
  console.log(`[${timestamp}] [${type}] ${message}`);
}

/**
 * Gets a sheet by name or creates it with headers if it doesn't exist.
 * @param {GoogleAppsScript.Spreadsheet.Spreadsheet} spreadsheet The active Google Spreadsheet.
 * @param {string} sheetName The name of the sheet to get or create.
 * @param {Array<string>} headers An array of strings for the header row if the sheet is created.
 * @returns {GoogleAppsScript.Spreadsheet.Sheet} The requested sheet.
 */
function getOrCreateSheet(spreadsheet, sheetName, headers) {
  let sheet = spreadsheet.getSheetByName(sheetName);
  if (!sheet) {
    sheet = spreadsheet.insertSheet(sheetName);
    sheet.appendRow(headers);
    sheet.setFrozenRows(1); // Freeze header row
  }
  return sheet;
}

/**
 * Handles spreadsheet edits to process approvals.
 * This function is automatically triggered by an onEdit event.
 * @param {GoogleAppsScript.Events.SheetsOnEdit} e The event object from the onEdit trigger.
 */
function onEdit(e) {
  const properties = PropertiesService.getScriptProperties();
  const VALIDATION_REPORT_SHEET_NAME = properties.getProperty('VALIDATION_REPORT_SHEET_NAME');
  const SCRIPT_LOG_SHEET_NAME = properties.getProperty('SCRIPT_LOG_SHEET_NAME');
  const GOOGLE_SHEET_ID = properties.getProperty('GOOGLE_SHEET_ID');

  const range = e.range;
  const sheet = range.getSheet();
  const sheetName = sheet.getName();

  // Only proceed if the edit is on the Validation Report sheet
  if (sheetName !== VALIDATION_REPORT_SHEET_NAME) {
    return;
  }

  const logSheet = getOrCreateSheet(SpreadsheetApp.openById(GOOGLE_SHEET_ID), SCRIPT_LOG_SHEET_NAME, ['Timestamp', 'Type', 'Message']);
  log(`onEdit triggered on ${sheetName} at row ${range.getRow()} col ${range.getColumn()}.`, 'INFO', logSheet);

  const headers = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getValues()[0];
  const approveCol = headers.indexOf('Approve?');
  const statusCol = headers.indexOf('Status');
  const issueKeyCol = headers.indexOf('Jira Issue Key');
  const fieldNameCol = headers.indexOf('Field Name');
  const proposedValueCol = headers.indexOf('Proposed Value (from Sheet)');
  const approvedByCol = headers.indexOf('Approved By');
  const approvedAtCol = headers.indexOf('Approved At');
  const appliedByCol = headers.indexOf('Applied By');
  const appliedAtCol = headers.indexOf('Applied At');

  // Check if the edited column is the 'Approve?' column and it's a checkbox that was checked
  if (approveCol === -1 || range.getColumn() - 1 !== approveCol || !range.isChecked()) {
    return; // Not the approve column, or checkbox was unchecked, or not a checkbox
  }

  // Ensure it's not the header row
  if (range.getRow() === 1) {
    return;
  }

  const row = sheet.getRange(range.getRow(), 1, 1, sheet.getLastColumn()).getValues()[0];
  const currentStatus = row[statusCol];

  if (currentStatus === 'Pending') {
    const issueKey = row[issueKeyCol];
    const fieldName = row[fieldNameCol];
    const proposedValue = row[proposedValueCol];
    const approverEmail = Session.getActiveUser().getEmail();
    const approvedAt = Utilities.formatDate(new Date(), Session.getScriptTimeZone(), 'yyyy-MM-dd HH:mm:ss');

    // Update status to 'Approved' and record approval info
    sheet.getRange(range.getRow(), statusCol + 1).setValue('Approved');
    sheet.getRange(range.getRow(), approvedByCol + 1).setValue(approverEmail);
    sheet.getRange(range.getRow(), approvedAtCol + 1).setValue(approvedAt);
    // Uncheck the 'Approve?' box so it doesn't re-trigger and visually indicates processing
    sheet.getRange(range.getRow(), approveCol + 1).setValue(false);

    log(`Approval received for ${issueKey} - ${fieldName} to ${proposedValue} by ${approverEmail}. Attempting to apply update.`, 'INFO', logSheet);

    const success = applyJiraUpdate(issueKey, fieldName, proposedValue, logSheet);

    if (success) {
      sheet.getRange(range.getRow(), statusCol + 1).setValue('Applied');
      sheet.getRange(range.getRow(), appliedByCol + 1).setValue('Automated Script');
      sheet.getRange(range.getRow(), appliedAtCol + 1).setValue(Utilities.formatDate(new Date(), Session.getScriptTimeZone(), 'yyyy-MM-dd HH:mm:ss'));
      log(`Successfully applied update for ${issueKey} - ${fieldName}.`, 'INFO', logSheet);
    } else {
      // If update failed, revert status to Approved (manual intervention needed) and re-check Approve? box
      sheet.getRange(range.getRow(), statusCol + 1).setValue('Approved (Failed to Apply)');
      sheet.getRange(range.getRow(), approveCol + 1).setValue(true); // Re-check to indicate it's still pending action
      log(`Failed to apply update for ${issueKey} - ${fieldName}. Manual intervention required.`, 'ERROR', logSheet);
    }
  } else if (currentStatus === 'Applied') {
      log(`Discrepancy for ${row[issueKeyCol]} - ${row[fieldNameCol]} is already Applied. No action taken.`, 'INFO', logSheet);
      // Automatically uncheck if it's already applied to prevent re-processing
      sheet.getRange(range.getRow(), approveCol + 1).setValue(false);
  } else {
      log(`Discrepancy for ${row[issueKeyCol]} - ${row[fieldNameCol]} has status '${currentStatus}'. No action taken on approval.`, 'INFO', logSheet);
      // Automatically uncheck if status is not 'Pending'
      sheet.getRange(range.getRow(), approveCol + 1).setValue(false);
  }
}

/**
 * Applies the approved update to Jira.
 * @param {string} issueKey The key of the Jira issue to update.
 * @param {string} fieldName The name of the field to update ('Dev Completion Date' or 'QA Sign-off Date').
 * @param {string} newValue The new date value (YYYY-MM-DD string).
 * @param {GoogleAppsScript.Spreadsheet.Sheet} logSheet The sheet for logging.
 * @returns {boolean} True if the update was successful, false otherwise.
 */
function applyJiraUpdate(issueKey, fieldName, newValue, logSheet) {
  const properties = PropertiesService.getScriptProperties();
  const JIRA_DEV_COMPLETION_DATE_FIELD_ID = properties.getProperty('JIRA_DEV_COMPLETION_DATE_FIELD_ID');
  const JIRA_QA_SIGNOFF_DATE_FIELD_ID = properties.getProperty('JIRA_QA_SIGNOFF_DATE_FIELD_ID');

  let customFieldId;
  if (fieldName === 'Dev Completion Date') {
    customFieldId = JIRA_DEV_COMPLETION_DATE_FIELD_ID;
  } else if (fieldName === 'QA Sign-off Date') {
    customFieldId = JIRA_QA_SIGNOFF_DATE_FIELD_ID;
  } else {
    log(`Unknown fieldName for Jira update: ${fieldName}`, 'ERROR', logSheet);
    return false;
  }

  const payload = {
    fields: {
      [customFieldId]: newValue // Jira expects ISO date string for date fields
    }
  };

  const endpoint = `/rest/api/3/issue/${issueKey}`;
  const response = makeJiraApiCall('PUT', endpoint, payload, logSheet);

  return response !== null; // If makeJiraApiCall returns null, it failed
}

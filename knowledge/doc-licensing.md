# DeskAgent Licensing

This documentation describes how DeskAgent is licensed and activated.

## License Model

DeskAgent uses a **session-based license model**:

- **Per device**: One license allows use on one device at a time
- **Device change**: License can be deactivated and activated on another device
- **Automatic resume**: After restart, the license is restored automatically

## Activation

### Step 1: Open Settings

Click the **gear icon** at the top right to open the settings.

### Step 2: Select License Tab

Select the **License** tab in the tab bar.

### Step 3: Choose Activation Method

There are two activation methods:

#### By Invoice

If you acquired DeskAgent via an invoice:

1. Select **"by invoice"**
2. Enter your **invoice number** (e.g. `RE-2025-0123`)
3. Enter your **ZIP code** (postal code of the billing address)
4. Enter your **email address**
5. Click **"Activate"**

#### By Code

If you received an activation code (e.g. SUB code for team members):

1. Select **"by code"**
2. Enter your **activation code** (format: `SUB-XXXX-YYYY-ZZZZ`)
3. Enter your **email address**
4. Click **"Activate"**

## Check License Status

The current license status is shown in the License tab:

| Status | Meaning |
|--------|---------|
| **ACTIVE** (green) | License is valid and active |
| **OFFLINE** (blue) | License runs in offline mode (server unreachable) |
| **OFFLINE** (orange) | Warning: offline time is about to expire |
| **INACTIVE** (red) | No active license |

### Displayed Information

- **Email**: The email address associated with the license
- **Device**: Name of the current computer
- **Device ID**: Unique ID for device identification
- **Valid until**: Expiration date of the license (if time-limited)

## Deactivation

To deactivate the license (e.g. for a device change):

1. Open **Settings** → **License**
2. Click the **"Deactivate"** button
3. The license is released on the server

**Note**: After deactivation, the license can be activated on another device.

## Offline Mode (Grace Period)

DeskAgent can also be run without an internet connection:

### How it works

1. On every successful connection to the license server, a timestamp is stored
2. If the server is unreachable, DeskAgent continues in **offline mode**
3. After **48 hours** without server connection, DeskAgent is blocked
4. From **8 hours** remaining time onward, a warning is shown

### On Connection Problems

If offline mode is shown:

1. Check your internet connection
2. Click **"Retry"** in the warning banner
3. Once the connection is restored, DeskAgent continues normally

### Important

- Initial activation requires an internet connection
- After successful activation, offline operation is possible
- Regular connections (at least every 48h) are recommended

## Team Licenses (SUB Codes)

For companies with multiple users:

### Obtain SUB Codes

1. The license owner logs in to the **customer portal**
2. Navigates to **"Team licenses"**
3. Generates new **SUB codes** for team members
4. The codes are distributed by email

### Use SUB Codes

Team members activate DeskAgent with:

1. Select **"by code"**
2. Enter the received **SUB code**
3. Enter own **email address**
4. Click **"Activate"**

**Note**: SUB codes count against the main account's quota.

## Troubleshooting

### "Server unreachable"

**Possible causes:**
- No internet connection
- Firewall blocks the connection
- Proxy settings missing

**Solution:**
1. Check internet connection
2. Allow DeskAgent in firewall
3. Configure proxy settings in system settings

### "Invalid credentials"

**Possible causes:**
- Invoice number entered incorrectly
- ZIP code does not match billing address
- Code has already been used

**Solution:**
1. Check invoice number on the original invoice
2. Use ZIP code of the **billing address** (not shipping address)
3. For code issues: contact support

### "Maximum number of devices reached"

**Cause:** The license is already active on another device.

**Solution:**
1. Deactivate on the other device
2. Or: manage all sessions in the customer portal

## Support

For license issues:

- **Email**: ask@deskagent.de

**Note:** This document describes the **Commercial Edition** activation flow. In the
**AGPL / Community Edition** (no `config/license.json`, no `app.license_api_url`
configured) the License tab and all activation endpoints are served by the
`NullLicenseProvider` and never perform network calls — no activation is required.

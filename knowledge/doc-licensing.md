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

---

## AGPL-3.0 Community Edition

When DeskAgent is run from source (the `deskagent-ai/community` GitHub
repo), without a `config/license.json` and without an
`app.license_api_url`, it operates in **AGPL-3.0 Community Edition**:

- The License tab still appears, but all of its endpoints are served by
  the `NullLicenseProvider`. They never call out to a license server.
- `is_licensed()` always returns `true`, `edition` reads `agpl`, and
  `check-agent` permits every agent.
- Activation, deactivation, and offline-grace flows are no-ops (`activate`
  responds with `{success: false, reason: "agpl_mode"}` so the UI button
  is correctly disabled).
- There is **nothing to register** — installing and running is enough.

### When AGPL Section 13 obligations apply

The AGPL-3.0 "remote network interaction" clause (Section 13) is the
only meaningful obligation in the Community Edition. It triggers only
when **both** of the following are true at the same time:

1. You **modified** DeskAgent (changed any of the source files in this
   repository), and
2. You **offer the modified version to other users over a network** —
   i.e. people other than you interact with your modified DeskAgent
   remotely.

Common scenarios in practice:

| Scenario | Section 13 triggered? | What to do |
|---|---|---|
| Run unmodified DeskAgent locally on your own PC | No | Nothing |
| Run DeskAgent on `localhost` only, you are the only user | No | Nothing |
| Run modified DeskAgent for yourself only, no remote users | No | Nothing |
| Run unmodified DeskAgent for a team behind your firewall, no source changes | No | Nothing |
| Run **modified** DeskAgent and give a team / customers remote access | **Yes** | Provide the modified source to those users, or buy a Commercial License |
| Host a public SaaS based on DeskAgent (modified or not, modifications usually accumulate) | **Yes** in practice | Same — provide source, or buy a Commercial License |

The relevant code path is `bind_host` in
[../scripts/assistant/server.py](../scripts/assistant/server.py).
Setting the environment variable `DESKAGENT_BIND_HOST=0.0.0.0`
exposes the local server to the network. When DeskAgent starts in
that mode, it emits the following log message intentionally:

```
AGPL Section 13 Notice: Running in network mode.
If you offer this service to remote users AND have modified DeskAgent,
you must provide source code access to those users.
```

### How to comply if Section 13 applies

Pick **one** of the following:

1. **Publish your modified source.** A public Git fork (preserving the
   AGPL header) satisfies the requirement. The link must be reachable
   by the users of your modified instance.
2. **Embed an offer in the UI.** Provide a clearly accessible link
   from inside the running DeskAgent (e.g. an "About" panel entry)
   pointing at the modified source.
3. **Buy a Commercial License from realvirtual GmbH.** This removes
   the AGPL obligations contractually so you can run modified
   DeskAgent privately as a network service without publishing
   changes. Contact info@realvirtual.io.

### What is NOT a modification

- Configuration files in `config/` are user data, not source modifications.
- Custom agents/skills in your `agents/` and `skills/` directories are
  your own work, not DeskAgent modifications.
- New plugins under `plugins/` that use the documented Plugin API are
  explicitly carved out by the **Plugin Exception** (see
  [`../LICENSE`](../LICENSE)) and can be proprietary even when
  installed alongside DeskAgent.
- Running on `localhost` only — even with browser-based access on the
  same machine — is not a "remote network interaction" in the AGPL
  sense.

### Source availability for the unmodified case

Even with no modifications, you must make the AGPL license text and a
pointer to the upstream source available to users of your network
deployment (AGPL §1, "Corresponding Source"). The shipped
[`../LICENSE`](../LICENSE) file and the link to
`github.com/deskagent-ai/community` in
[`../README.md`](../README.md) are sufficient for this.

### Commercial Edition (this document)

The sections above this notice describe the **Commercial Edition**
activation flow. The Commercial License is what the buyer of a signed
installer obtains. It removes the AGPL-3.0 source-disclosure obligation
in exchange for a paid license, providing the same code under
proprietary terms. Contact info@realvirtual.io for pricing and
availability.

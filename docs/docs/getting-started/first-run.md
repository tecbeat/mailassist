# First Run

After [installation](installation.md), open `http://localhost:8000` and log in through your OIDC provider.

## 1. Add a Mail Account

Navigate to **Mail Accounts** and click **Add Account**.

- **Name**: A label for this account (e.g. "Work")
- **Email Address**: The email address
- **IMAP Host/Port**: Your IMAP server (e.g. `imap.gmail.com:993`)
- **SSL/TLS**: Enable for port 993
- **Username/Password**: IMAP credentials (stored with envelope encryption)

Click **Save**, then **Test Connection** to verify.

## 2. Add an AI Provider

Navigate to **AI Providers** and click **Add Provider**.

- **Provider Type**: OpenAI or Ollama
- **Base URL**: API endpoint (e.g. `http://ollama:11434` for local Ollama)
- **Model**: Model name (e.g. `gemma3:12b`)
- **API Key**: Required for OpenAI, optional for Ollama

Click **Save**, then **Test Connection**.

## 3. Configure Plugins

Navigate to **Plugins** to see the processing pipeline. Each plugin has three modes:

- **Auto**: Actions are applied automatically
- **Approval**: Actions are queued for your review
- **Off**: Plugin is disabled

!!! tip
    Start with everything in **Approval** mode. Watch the queue for a few days, then flip trusted plugins to **Auto**.

## 4. Check the Approval Queue

Navigate to **Approvals** to review pending AI actions. For each item you can:

- **Approve**: Apply the action
- **Edit before approving**: Modify the action, then approve
- **Reject**: Discard the action

## 5. Customize Prompts (Optional)

Navigate to **Prompts** to edit the Jinja2 templates that control how each plugin instructs the LLM. The editor supports syntax highlighting and shows available template variables.

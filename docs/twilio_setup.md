# Twilio Setup Guide for Contraception DSS

To get the Contraception DSS communicating via WhatsApp, you need to set up a Twilio account and configure its WhatsApp Sandbox. This guide will walk you through the process step-by-step.

## Step 1: Create a Twilio Account
1. Go to [Twilio's website](https://www.twilio.com/) and click **Sign Up** (or "Start for free").
2. Fill in your details (Name, Email, Password) and verify your email address.
3. Verify your phone number. Twilio needs this to send you text messages and for account security.
4. During the onboarding questionnaire, select:
   - **Which product are you here to use?** SMS / WhatsApp
   - **What do you plan to build with Twilio?** Chatbot
   - **How do you want to build with Twilio?** With code
   - **What is your preferred coding language?** Python

## Step 2: Get your API Credentials
Once you are on the Twilio Console (dashboard):
1. In the top left or center of your dashboard, you will see your **Account Info**.
2. Locate the **Account SID** and **Auth Token**. You need to click the "copy" icon or "show" to see the auth token.
3. Open the `mhc-backend/.env` file in your project and add these credentials:
   ```env
   TWILIO_ACCOUNT_SID=your_account_sid_here
   TWILIO_AUTH_TOKEN=your_auth_token_here
   ```

## Step 3: Activate the WhatsApp Sandbox
Since getting a dedicated WhatsApp Business number requires Meta approval, we use the Sandbox for testing.
1. In the Twilio Console menu (left sidebar), go to **Messaging** > **Try it out** > **Send a WhatsApp message**.
2. Accept the terms to activate the sandbox.
3. You will see a Twilio WhatsApp phone number and a join code (e.g., "Join secret-word").
4. On your personal phone, send a WhatsApp message with that exact join code to the Twilio number.
5. You should receive a reply saying you are "all set" and connected to the sandbox.

## Step 4: Expose your Local Server to the Internet (Ngrok)
Twilio needs a public URL to send incoming messages to your Python script. Since your script is running locally (e.g., `http://localhost:8080`), you must use a tool like Ngrok.
1. Download and install [Ngrok](https://ngrok.com/).
2. Run your Flask app: `python main.py` (ensure you are in the `mhc-backend` folder).
3. Open a new terminal window and run: `ngrok http 8080`.
4. Ngrok will provide a public URL that looks like `https://<random-characters>.ngrok-free.app`. Copy this **Forwarding URL**.

## Step 5: Configure the Webhook
Now you tell Twilio where to send incoming WhatsApp messages.
1. Go back to the Twilio Console.
2. Navigate to **Messaging** > **Settings** > **WhatsApp Sandbox Settings**.
3. Under the **"WHEN A MESSAGE COMES IN"** field, paste your Ngrok URL and append `/webhook` to the end.
   - Example: `https://<random-characters>.ngrok-free.app/webhook`
4. Ensure the HTTP method is set to **HTTP POST**.
5. Click **Save** at the bottom.

## Step 6: Test the Bot!
Send a message like "Habari" from your phone to the Twilio WhatsApp Sandbox number. 
If everything is set up correctly:
1. Your phone sends the message to Twilio.
2. Twilio forwards it to your Ngrok URL.
3. Ngrok routes it to your local Flask app (`main.py`).
4. `main.py` processes the message and sends a response back through Twilio to your phone!

## Step 7: Enable Interactive Buttons (Required for Menus)

Plain text works without this step, but **tappable buttons** need Twilio Content templates.

See **[twilio_content_templates.md](./twilio_content_templates.md)** — create 5 templates (2-button, 3-button, 4-row, 5-row, 7-row list) and add the Content SIDs to `.env`.

Restart `python main.py` and confirm the startup log shows all templates as `set`.

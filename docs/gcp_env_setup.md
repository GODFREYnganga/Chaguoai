# Getting Your GCP `.env` Variables & Running the App

Since you have already enabled the necessary APIs in Google Cloud, here is exactly how to get the variables for your `.env` file, and how you should run the app for testing.

## 1. How to get the GCP `.env` variables

### `GCP_PROJECT_ID`
1. Go to your [Google Cloud Console](https://console.cloud.google.com/).
2. Look at the top-left corner, right next to the "Google Cloud" logo. Click the project dropdown.
3. Find your project in the list. The **Project ID** is usually a string with lowercase letters and numbers (e.g., `mhc-project-12345`). Copy that ID into your `.env`.

### `GOOGLE_APPLICATION_CREDENTIALS` (The JSON Key)
To let your local `main.py` code securely talk to your Cloud Firestore database and Vertex AI, you need a Service Account Key.
1. In the Google Cloud Console, search for **Service Accounts** in the top search bar.
2. Click **Create Service Account** at the top.
3. Name it `backend-sa` and click **Create and Continue**.
4. Important: Under **Select a role**, grant it the following roles:
   * **Editor** (For testing purposes, this gives it access to everything like Firestore and Vertex).
5. Click **Done**.
6. Find the new service account in the list, click the three dots (`⋮`) under Actions, and select **Manage keys**.
7. Click **ADD KEY** -> **Create new key** -> Choose **JSON** and click **Create**.
8. A `.json` file will download to your computer.
9. **Action:** Move this `.json` file into your `c:\Users\Admin\Desktop\MHC\backend` folder. Rename it to something simple, like `mhc-gcp-key.json`.
10. In your `.env` file, set `GOOGLE_APPLICATION_CREDENTIALS=./mhc-gcp-key.json`

### `GEMINI_API_KEY`
1. Go to [Google AI Studio](https://aistudio.google.com/app/apikey) (which uses your GCP project).
2. Click **Get API key**.
3. Create an API key for your `MHC-Project`.
4. Copy the key and paste it into `GEMINI_API_KEY` in your `.env`.

---

## 2. Should you run `main.py` locally or in the cloud?

**For testing and development right now, you MUST run it locally.** Here is why:

When you are testing, you will be constantly tweaking the bot's responses. 
If you put it in the cloud immediately, you would have to redeploy it to Google Cloud every time you change a single line of code, which is very slow.

### The Testing Workflow (Local + Ngrok)
1. You run the app on your laptop: `python main.py`
2. Your app is now running on your laptop at `http://localhost:8080`. (But Twilio cannot see your laptop directly).
3. You run **Ngrok** in a separate terminal: `ngrok http 8080`.
4. Ngrok creates a temporary public URL, like a tunnel straight to your laptop (e.g., `https://1234.ngrok-free.app`). 
5. You paste `https://1234.ngrok-free.app/webhook` into the Twilio Sandbox.

*Advantages of testing locally:* If you get an error, you can see the traceback immediately in your terminal! You can also stop `main.py`, edit the code, and restart it in 2 seconds. The Twilio Sandbox still works perfectly this way because Ngrok acts as the bridge.

### The Production Workflow (The Cloud)
Once the chatbot is completely finished, perfectly tested, and ready for actual users:
1. You will deploy `backend` to **Google Cloud Run** or **Google Cloud Functions**.
2. Google Cloud will give you a permanent, live URL (e.g., `https://backend-xyz.a.run.app`).
3. You will go back into Twilio and replace the Ngrok URL with this permanent Cloud URL.
4. From then on, the chatbot will run 24/7 in the cloud, and you won't need your laptop open!

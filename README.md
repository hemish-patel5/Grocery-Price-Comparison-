# 🛒 NZ Grocery Price Comparison App

A full-stack web application designed to help New Zealand shoppers compare real-time prices across major local retailers, including **PAK'nSAVE**, **New World**, and **Woolworths**.

---

## 🚀 Features
* **Live Price Fetching:** Queries multiple NZ supermarket APIs simultaneously for real-time data.
* **Smart Highlighting:** Automatically identifies the "Cheapest Found" item and displays it in a featured Hero Card.
* **Branded UI:** Custom "Pill" design for store labels (Yellow for PAK'nSAVE, Green for Woolworths) for instant visual recognition.
* **Modern Tech Stack:** Fast, responsive interface built with Vite and Tailwind CSS.

---

## ⚙️ Setup and Installation
Follow these steps to get the project running locally on your machine.

### 1. Prerequisites
* [ ] **Python 3.10+** installed.
* [ ] **Node.js (v18+)** and **npm** installed.

### 2. Backend Setup (Flask)
Open a terminal in the project root folder and run:

```bash
# Navigate to the backend directory
cd backend

# Install necessary Python dependencies
pip install -r requirements.txt

# Start the Flask server
python app.py
```

### 3. Frontend Setup (React + Vite)
Open a new terminal window and run:

```bash
# Navigate to frontend
cd frontend

# Install Node modules
npm install

# Start the development server
npm run dev
```
### Note: The application will be accessible in your browser at http://localhost:5173

---

## 🛠️ Tech Stack

### Frontend
* **React.js** (Vite)
* **Tailwind CSS** (Styling & Responsive Design)
* **Lucide React** (Iconography)

### Backend
* **Python / Flask** (REST API)
* **HTTPX** (Asynchronous web requests for high-performance scraping)
* **Flask-CORS** (Cross-Origin Resource Sharing)

---

## 📂 Project Structure

```text
.
├── backend/
│   ├── app.py              # Flask server and scraping logic
│   └── requirements.txt    # Python dependencies (Flask, HTTPX, etc.)
├── frontend/
│   ├── src/
│   │   ├── App.jsx         # Main React application logic
│   │   └── index.css       # Tailwind directives and custom styles
│   ├── package.json        # Node.js dependencies and scripts
│   └── vite.config.js      # Vite configuration
└── .gitignore              # Root-level git ignore rules

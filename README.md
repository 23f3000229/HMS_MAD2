# Hospital Management System

My MAD2 Project on Hospital Management System.
A full-stack web application for managing hospital operations including appointments, treatments, and user roles.

## Tech Stack

**Backend:** Flask, Flask-RESTful, Flask-Security, SQLAlchemy  
**Frontend:** Vue 3, Vite, Pinia

## Quick Start

### rerequisites

-Python 3.8+
-Node.js 14+
-pip, npm

### Backend Setup

 1.Navigate to the backend folder:

```bash
   cd backend
   ```

2.Create a virtual environment:

   ```bash
   python -m venv venv
   ```

3.Activate virtual environment:

- **Windows:**

    ```bash
     venv\Scripts\activate
     ```

- **Mac/Linux:**

     ```bash
     source venv/bin/activate
     ```

4.Install dependencies:

 ```bash
   pip install -r requirements.txt
   ```

5.Run the Flask server:

```bash
   python app.py
   ```

Server runs on: `http://127.0.0.1:5000`

### Frontend Setup

1. Navigate to the frontend folder:

   ```bash
   cd frontend
   ```

2. Install dependencies:

   ```bash
   npm install
   ```

3. Run the development server:

   ```bash
   npm run dev
   ```

   Frontend runs on: `http://localhost:5173`

## Default Login

- **Email:** <admin@hospital.com>

## Features

- **User Roles:** Admin, Doctor, Patient
- **Departments & Doctors:** Manage healthcare departments
- **Appointments:** Schedule and track appointments
- **Treatments:** Record treatment details and prescriptions
- **Doctor Availability:** Set doctor schedules

## API Endpoints

All API endpoints are prefixed with `/api/`. See backend controller files for detailed endpoint documentation.

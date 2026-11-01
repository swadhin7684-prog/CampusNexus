# Third-Party Libraries & Solvers Declaration (THIRD_PARTY.md)
**Project:** CampusNexus — Chilika Institute of Technology (CIT)  
**Challenge:** Crunch Week Scheduling & Venue Management Platform  

In compliance with Section 6 of the Official Problem Statement, this document lists all open-source libraries, solvers, and frameworks used in this project. All code in this repository was written during the hackathon period from scratch.

---

## 1. Solvers & Core Algorithms

* **Google OR-Tools (`ortools`)**  
  * **License:** Apache 2.0  
  * **Purpose:** Core Constraint Programming solver (`CP-SAT`). Used for formulating and solving the full college timetable, Midsem examinations scheduling, and minimal-churn disruption repair.

---

## 2. Backend & API Stack

* **FastAPI (`fastapi`)**  
  * **License:** MIT  
  * **Purpose:** High-performance asynchronous REST API framework for timetable queries, event bookings, disruption simulation, and validator orchestration.
* **Uvicorn (`uvicorn`)**  
  * **License:** BSD-3-Clause  
  * **Purpose:** Lightning-fast ASGI web server.
* **Pydantic (`pydantic`)**  
  * **License:** MIT  
  * **Purpose:** Data validation and structured schemas for request/response payloads.
* **Python-Dotenv (`python-dotenv`)**  
  * **License:** BSD-3-Clause  
  * **Purpose:** Loading configuration and environment variables.
* **Pandas (`pandas`)**  
  * **License:** BSD-3-Clause  
  * **Purpose:** Data manipulation and analysis of supplied CSV tabular files.

---

## 3. Frontend Stack

* **React (`react`, `react-dom`)**  
  * **License:** MIT  
  * **Purpose:** Interactive user interface for timetable visualization, role-based workflows, and booking forms.
* **Vite (`vite`)**  
  * **License:** MIT  
  * **Purpose:** Ultra-fast modern frontend build tool and development server.
* **Tailwind CSS (`tailwindcss`)**  
  * **License:** MIT  
  * **Purpose:** Utility-first responsive CSS styling for dashboard and timetable grids.
* **Lucide React (`lucide-react`)**  
  * **License:** ISC  
  * **Purpose:** Clean, modern UI iconography.


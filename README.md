# NutriAI — Diet Plan Service

The **Diet Service** is the analytical core of the NutriAI application. It integrates patient health records, clinical document scans, and AI models to generate customized weekly meal schedules, nutritional constraints, and PDF export reports. It also publishes automated meal alerts asynchronously to **Azure Service Bus**.

---

## 🏗️ Core Role & Functionality
1. **Clinical Profile Aggregation**: Queries the shared database to retrieve the patient's age, weight, height, medical histories, food allergies, and selected document OCR scans.
2. **AI Diet Recommendation**: Templates clinical data into structured instructions and prompts the **Azure OpenAI Service** (GPT deployment) to output a validated JSON schema containing food recommendations and meal schedules.
3. **Meal Notification Schedules**: Triggers after plan generation. Formulates meal schedules for the upcoming week and publishes asynchronous messages to the **Azure Service Bus** topic (`email-notifications`).
4. **PDF Generator**: Compiles generated meal charts, nutritional metrics, and allergy alerts into a downloadable print-formatted PDF report using `ReportLab`.

---

## 🛠️ Technology Stack
* **Framework**: [FastAPI](https://fastapi.tiangolo.com/) (Python 3.12)
* **AI Integration**: [OpenAI Python SDK](https://github.com/openai/openai-python) (AzureOpenAI client wrapper)
* **Messaging Broker**: [Azure Service Bus SDK](https://github.com/Azure/azure-sdk-for-python/tree/main/sdk/servicebus/azure-servicebus)
* **Auth Identity**: [Azure Identity SDK](https://github.com/Azure/azure-sdk-for-python/tree/main/sdk/identity/azure-identity) (`DefaultAzureCredential`)
* **PDF Compiler**: [ReportLab PDF Library](https://www.reportlab.com/)
* **ORM & DB**: [SQLAlchemy](https://www.sqlalchemy.org/) & [Psycopg2](https://www.psycopg.org/)

---

## ⚙️ Configuration & Environment Variables

Variables are loaded in [app/config.py](file:///c:/Users/YASWANTH/cloudtrack_final/NutriAI-diet-service/app/config.py):

| Variable Name | Default Value | Description |
| :--- | :--- | :--- |
| `DATABASE_URL` | `sqlite:///./test.db` | Shared PostgreSQL connection string. |
| `AZURE_OPENAI_ENDPOINT` | *Empty* | Azure OpenAI resource endpoint. |
| `AZURE_OPENAI_KEY` | *Empty* | Azure OpenAI API access key. |
| `AZURE_OPENAI_DEPLOYMENT_NAME` | `gpt-5.1` | Deployment name/model ID. |
| `AZURE_OPENAI_API_VERSION` | `2024-02-01` | Azure OpenAI API version. |
| `AZURE_SERVICE_BUS_CONNECTION_STRING` | *Empty* | Connection string for local debugging. |
| `AZURE_SERVICE_BUS_FULLY_QUALIFIED_NAMESPACE` | *Empty* | Service Bus host (e.g. `*.servicebus.windows.net`) used in production via Workload Identity. |
| `AZURE_SERVICE_BUS_TOPIC_NAME` | `email-notifications` | Target queue topic for scheduling. |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | *Empty* | Application Insights connection string. |

---

## 🗄️ Database Models

The service references the following models defined in [app/models.py](file:///c:/Users/YASWANTH/cloudtrack_final/NutriAI-diet-service/app/models.py):
* **User**: Base credentials and biometric fields (height, weight, age).
* **PatientProfile**: Stores list fields of medical conditions and dietary preferences.
* **FoodAllergy**: Tracks allergens and severity warnings.
* **Document**: Scanned clinical files containing OCR contents.
* **DietPlan**: The generated output record storing weekly plans, guidelines, food lists, and activity flags.

---

## 🔌 API Endpoints Reference

All routes are declared in [app/routes.py](file:///c:/Users/YASWANTH/cloudtrack_final/NutriAI-diet-service/app/routes.py).

| HTTP Method | Route | Description | Auth Header Required |
| :--- | :--- | :--- | :--- |
| **GET** | `/diet-plan/documents` | Returns all completed document scans available for the user. | `X-User-ID` |
| **POST** | `/diet-plan/generate` | Orchestrates context assembly, queries OpenAI, saves plan to DB, publishes notifications, and returns plan JSON. | `X-User-ID` |
| **GET** | `/diet-plan/history` | Lists all past diet plans generated for the user. | `X-User-ID` |
| **GET** | `/diet-plan/{plan_id}` | Returns details of a specific diet plan. | `X-User-ID` |
| **GET** | `/diet-plan/{plan_id}/pdf` | Builds and streams a binary PDF report file. | `X-User-ID` |

---

## 🔄 Messaging & Azure Resource Integration

### 1. Azure OpenAI Integration
The service connects to Azure OpenAI to execute clinical analyses:
* Prompts specify strict output schemas to verify that response JSON contains fields like `foods_to_eat`, `foods_to_avoid`, `weekly_meal_plan` (divided by breakfast, lunch, dinner, snack for days Monday-Sunday), and `nutritional_guidelines`.

### 2. Azure Service Bus Integration
* Upon successful generation, the service initializes a `ServiceBusClient`.
* In AKS, authentication is handled via **Workload Identity** (no connection strings are used). The client connects using `DefaultAzureCredential()` and publishes message envelopes containing target email, subject, plan metadata, and scheduled meal timings.

---

## 🚀 CI/CD Pipeline
* Pipeline: [.github/workflows/cicd.yml](file:///c:/Users/YASWANTH/cloudtrack_final/NutriAI-diet-service/.github/workflows/cicd.yml).
* Uses reusable shared pipelines: format verification, unit testing, SonarQube quality gate and Snyk vulnerability scans, Trivy container validation, push to ACR, and updates the manifests repository (`helm/nutriai/values-{env}.yaml`).

---

## 💻 Local Development

```bash
# Install packages
pip install -r requirements.txt

# Run diet service locally (starts on port 8003)
uvicorn app.main:app --port 8003 --reload
```
Access at `http://127.0.0.1:8003`.

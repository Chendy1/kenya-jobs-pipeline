"""Dictionary-based skill extraction.

SKILLS = name: (category, aliases matched case-insensitively, aliases matched case-SENSITIVELY).
Ambiguous words ("Spark", "Excel", "React") go in the case-sensitive list so that
"excel in customer service" or "spark creativity" doesn't count.
Extend this dict as you see gaps in the data.
"""
from __future__ import annotations

import re

SKILLS: dict[str, tuple[str, list[str], list[str]]] = {
    # languages
    "Python": ("language", ["python"], []),
    "SQL": ("language", ["sql", "t sql", "tsql", "pl sql", "pl/sql", "plsql"], []),
    "R": ("language", ["r programming", "r language", "rstudio", "r studio"], []),
    "Java": ("language", ["java"], []),
    "JavaScript": ("language", ["javascript", "java script", "ecmascript"], []),
    "TypeScript": ("language", ["typescript"], []),
    "C#": ("language", ["c#", "c sharp", "csharp"], []),
    "C++": ("language", ["c++"], []),
    "PHP": ("language", ["php"], []),
    "Go": ("language", ["golang"], []),
    "Ruby": ("language", ["ruby", "ruby on rails"], []),
    "Kotlin": ("language", ["kotlin"], []),
    "Swift": ("language", [], ["Swift"]),
    "Scala": ("language", ["scala"], []),
    "Bash": ("language", ["bash", "shell scripting"], []),
    "VBA": ("language", ["vba"], []),
    # databases
    "PostgreSQL": ("database", ["postgresql", "postgres"], []),
    "MySQL": ("database", ["mysql"], []),
    "SQL Server": ("database", ["sql server", "mssql", "ms sql", "microsoft sql"], []),
    "Oracle DB": ("database", ["oracle database", "oracle db"], []),
    "MongoDB": ("database", ["mongodb", "mongo db"], []),
    "Redis": ("database", ["redis"], []),
    "SQLite": ("database", ["sqlite"], []),
    "Elasticsearch": ("database", ["elasticsearch", "elastic search"], []),
    "Cassandra": ("database", ["cassandra"], []),
    "DynamoDB": ("database", ["dynamodb"], []),
    "NoSQL": ("database", ["nosql"], []),
    # cloud & warehouses
    "AWS": ("cloud", ["aws", "amazon web services"], []),
    "Azure": ("cloud", ["azure"], []),
    "GCP": ("cloud", ["gcp", "google cloud"], []),
    "Redshift": ("cloud", ["redshift"], []),
    "Snowflake": ("cloud", ["snowflake"], []),
    "BigQuery": ("cloud", ["bigquery", "big query"], []),
    "Databricks": ("cloud", ["databricks"], []),
    # data engineering
    "Spark": ("data_eng", ["pyspark", "apache spark", "spark sql", "spark streaming"], ["Spark"]),
    "Hadoop": ("data_eng", ["hadoop", "hdfs"], []),
    "Kafka": ("data_eng", ["kafka"], []),
    "Airflow": ("data_eng", ["airflow"], []),
    "dbt": ("data_eng", ["dbt", "data build tool"], []),
    "ETL": ("data_eng", ["etl", "elt"], []),
    "Data Warehousing": ("data_eng", ["data warehouse", "data warehouses", "data warehousing"], []),
    "Data Modeling": ("data_eng", ["data modeling", "data modelling", "dimensional modeling",
                                   "dimensional modelling", "star schema"], []),
    "Data Pipelines": ("data_eng", ["data pipeline", "data pipelines"], []),
    "Pandas": ("data_eng", ["pandas"], []),
    "NumPy": ("data_eng", ["numpy"], []),
    # BI & analytics
    "Power BI": ("bi_analytics", ["power bi", "powerbi"], []),
    "Tableau": ("bi_analytics", ["tableau"], []),
    "Looker": ("bi_analytics", ["looker", "looker studio", "data studio"], []),
    "Qlik": ("bi_analytics", ["qlik", "qlikview", "qlik sense"], []),
    "Excel": ("bi_analytics", ["ms excel", "microsoft excel", "advanced excel", "excel spreadsheets",
                               "excel formulas", "pivot table", "pivot tables", "vlookup"], ["Excel"]),
    "Google Sheets": ("bi_analytics", ["google sheets"], []),
    "SPSS": ("bi_analytics", ["spss"], []),
    "SAS": ("bi_analytics", [], ["SAS"]),
    "Stata": ("bi_analytics", ["stata"], []),
    "Data Visualization": ("bi_analytics", ["data visualization", "data visualisation"], []),
    "Data Analysis": ("bi_analytics", ["data analysis", "data analytics"], []),
    "Statistics": ("bi_analytics", ["statistics", "statistical analysis"], []),
    # ML / AI
    "Machine Learning": ("ml_ai", ["machine learning"], []),
    "Deep Learning": ("ml_ai", ["deep learning"], []),
    "NLP": ("ml_ai", ["nlp", "natural language processing"], []),
    "TensorFlow": ("ml_ai", ["tensorflow"], []),
    "PyTorch": ("ml_ai", ["pytorch"], []),
    "scikit-learn": ("ml_ai", ["scikit learn", "sklearn"], []),
    "Generative AI": ("ml_ai", ["generative ai", "genai", "llm", "llms", "large language model",
                                "large language models"], []),
    "Computer Vision": ("ml_ai", ["computer vision"], []),
    # web & apps
    "React": ("web", ["reactjs", "react js", "react.js", "react native"], ["React"]),
    "Angular": ("web", ["angular", "angularjs"], []),
    "Vue": ("web", ["vue", "vuejs", "vue.js"], []),
    "Node.js": ("web", ["node.js", "nodejs", "node js"], []),
    "Django": ("web", ["django"], []),
    "Flask": ("web", [], ["Flask"]),
    "FastAPI": ("web", ["fastapi", "fast api"], []),
    "Laravel": ("web", ["laravel"], []),
    "Spring Boot": ("web", ["spring boot", "springboot"], []),
    ".NET": ("web", [".net", "dotnet", "asp.net"], []),
    "REST APIs": ("web", ["rest api", "rest apis", "restful"], []),
    "GraphQL": ("web", ["graphql"], []),
    "HTML/CSS": ("web", ["html", "css", "html5", "css3"], []),
    "WordPress": ("web", ["wordpress"], []),
    "Flutter": ("web", ["flutter"], []),
    # devops
    "Docker": ("devops", ["docker"], []),
    "Kubernetes": ("devops", ["kubernetes", "k8s"], []),
    "Terraform": ("devops", ["terraform"], []),
    "Git": ("devops", ["git", "github", "gitlab"], []),
    "CI/CD": ("devops", ["ci/cd", "cicd", "jenkins", "github actions", "gitlab ci"], []),
    "Linux": ("devops", ["linux", "ubuntu", "red hat", "rhel"], []),
    "Ansible": ("devops", ["ansible"], []),
    # IT operations
    "Cisco": ("it_ops", ["cisco", "ccna", "ccnp"], []),
    "Networking": ("it_ops", ["network administration", "lan/wan", "tcp/ip", "routing and switching"], []),
    "Active Directory": ("it_ops", ["active directory"], []),
    "VMware": ("it_ops", ["vmware", "virtualization", "virtualisation"], []),
    "Windows Server": ("it_ops", ["windows server"], []),
    "Cybersecurity": ("it_ops", ["cybersecurity", "cyber security", "information security", "infosec"], []),
    "ITIL": ("it_ops", ["itil"], []),
    "Technical Support": ("it_ops", ["helpdesk", "help desk", "technical support", "it support"], []),
    # ERP, finance, business tools
    "SAP": ("erp_finance", ["sap erp", "sap hana", "sap fico", "sap s/4hana"], ["SAP"]),
    "QuickBooks": ("erp_finance", ["quickbooks", "quick books"], []),
    "Sage": ("erp_finance", ["sage 300", "sage evolution", "sage pastel", "pastel"], ["Sage"]),
    "Dynamics 365": ("erp_finance", ["dynamics 365", "dynamics nav", "business central", "navision"], []),
    "Odoo": ("erp_finance", ["odoo"], []),
    "IFRS": ("erp_finance", ["ifrs"], []),
    "Salesforce": ("business_tools", ["salesforce"], []),
    "CRM": ("business_tools", ["crm"], []),
    "Project Management": ("business_tools", ["project management", "pmp", "prince2"], []),
    "Agile": ("business_tools", ["agile", "scrum", "kanban"], []),
    "Jira": ("business_tools", ["jira"], []),
    "SEO": ("business_tools", ["seo"], []),
    "Google Analytics": ("business_tools", ["google analytics", "ga4"], []),
    "Figma": ("business_tools", ["figma"], []),
    "Microsoft Office": ("business_tools", ["microsoft office", "ms office", "office 365", "ms word",
                                            "microsoft word", "ms powerpoint", "microsoft powerpoint"], []),
}

_LB = r"(?<![A-Za-z0-9+#.])"
_LA = r"(?![A-Za-z0-9+#])"


def _build(aliases: list[str]):
    if not aliases:
        return None
    body = "|".join(re.escape(a) for a in sorted(aliases, key=len, reverse=True))
    return re.compile(f"{_LB}(?:{body}){_LA}")


_COMPILED = [(n, cat, _build(strong), _build(cs)) for n, (cat, strong, cs) in SKILLS.items()]


def extract_skills(text: str | None) -> list[tuple[str, str]]:
    """Return [(skill, category), ...] found in the text."""
    if not text:
        return []
    spaced = re.sub(r"[-_]", " ", text)  # "Power-BI" -> "Power BI"
    lowered = spaced.lower()
    return [
        (name, cat)
        for name, cat, strong, cs in _COMPILED
        if (strong and strong.search(lowered)) or (cs and cs.search(spaced))
    ]
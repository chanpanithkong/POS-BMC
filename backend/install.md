py -3.12 -m venv .venv
.venv\Scripts\python.exe -m 
pip install -r requirements-dev.txt
Copy-Item .env.example .env



.venv\Scripts\python.exe -m scripts.create_databases
.venv\Scripts\alembic.exe upgrade head
.venv\Scripts\python.exe -m scripts.bootstrap
.venv\Scripts\python.exe -m app.serve


$env:DB_NAME="pims_demo"; 


#run server
.venv\Scripts\python.exe -m app.serve
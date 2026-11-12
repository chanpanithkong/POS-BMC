py -3.12 -m venv .venv
 .\.venv\Scripts\activate -m 
pip install -r requirements-dev.txt
Copy-Item .env.example .env



python -m scripts.create_databases
.venv\Scripts\alembic.exe upgrade head
python -m scripts.bootstrap
python -m app.serve


$env:DB_NAME="pims_demo_store"; 


#run server
python -m app.serve
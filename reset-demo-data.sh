rm -r __pycache__
rm -r src/__pycache__
rm -r src/routes/__pycache__
rm data/renewals.db
rm -r migrations
flask db init
flask db migrate -m "Initial migration"
flask db upgrade
flask init-db
flask seed-db

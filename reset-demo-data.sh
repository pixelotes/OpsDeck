rm data/renewals.db
rm migrations/*
flask db init
flask db migrate -m "Initial migration"
flabk db upgrade
flask init-db
flask seed-db

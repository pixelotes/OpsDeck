rm data/renewals.db
rm -r migrations
flask db init
flask db migrate -m "Initial migration"
flask db upgrade
flask init-db
flask seed-db

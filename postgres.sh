docker run -d \
  --name postgres-container \
  -e POSTGRES_USER=admin \
  -e POSTGRES_PASSWORD=11223344ABC \
  -e POSTGRES_DB=dolphindb_cloud \
  -p 15432:5432 \
  postgres

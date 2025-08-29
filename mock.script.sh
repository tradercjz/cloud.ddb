curl -X POST "http://127.0.0.1:8001/api/v1/auth/token" -H "Content-Type: application/x-www-form-urlencoded" -d "username=admin" -d "password=JZJZ112233"
export TOKEN= 
curl -X POST "http://127.0.0.1:8001/api/v1/environments/" -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"spec_cpu": 2, "spec_memory": 4, "lifetime_hours": 1}'
curl -X GET "http://127.0.0.1:8001/api/v1/environments/" -H "Authorization: Bearer $TOKEN"

curl -X GET "http://127.0.0.1:8001/api/v1/environments/ddb-env-c186d093/connection" \
-H "Authorization: Bearer $TOKEN"


curl -X GET "http://127.0.0.1:8001/api/v1/environments/ddb-env-c186d093/schema" \
-H "Authorization: Bearer $TOKEN"
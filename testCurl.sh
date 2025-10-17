curl -X POST "http://127.0.0.1:8001/api/v1/auth/register" \
-H "Content-Type: application/json" \
-d '{   
"email": "jinzhi.chen@dolphindb.com",
"password": "DolphinDB123"
}'



curl -X POST "http://127.0.0.1:8001/api/v1/auth/token" \
-H "Content-Type: application/x-www-form-urlencoded" \
-d "username=jinzhi.chen@dolphindb.com&password=DolphinDB123"


curl -X POST "http://127.0.0.1:8001/api/v1/auth/verify-email" \
-H "Content-Type: application/json" \
-d '{
"email": "jinzhi.chen@dolphindb.com",
"code": "395306"
}'


curl -X POST "http://127.0.0.1:8001/api/v1/auth/resend-verification-email" \
-H "Content-Type: application/json" \
-d '{
"email": "jinzhi.chen@dolphindb.com"
}'
curl -i -X POST http://10.1.1.11:8083/connectors/ \
    -H "Accept:application/json" \
    -H "Content-Type:application/json" \
    -d @connector/teko.billing.json

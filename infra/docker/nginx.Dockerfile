FROM nginx:1.27-alpine

RUN apk add --no-cache openssl curl

COPY infra/nginx/default.conf /etc/nginx/conf.d/default.conf
COPY infra/nginx/entrypoint.sh /entrypoint.sh

RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
CMD ["nginx", "-g", "daemon off;"]

FROM nginx:1.27-alpine

RUN apk add --no-cache openssl

COPY 15-generate-self-signed-cert.sh /docker-entrypoint.d/15-generate-self-signed-cert.sh
COPY templates/default.conf.template /etc/nginx/templates/default.conf.template

# Checkout on Windows may turn LF into CRLF; sh refuses such scripts.
RUN sed -i 's/\r$//' /docker-entrypoint.d/15-generate-self-signed-cert.sh /etc/nginx/templates/default.conf.template \
    && chmod +x /docker-entrypoint.d/15-generate-self-signed-cert.sh

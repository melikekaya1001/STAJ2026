FROM nginx:stable-alpine3.24-perl

LABEL creator="melikekaya <mai.portal001@gmail.com>"

ENV KULLANICI="Melike"

ARG RENK


RUN apk update && apk add curl htop wget

WORKDIR /gecici
ADD https://wordpress.org/latest.tar.gz .

WORKDIR /usr/share/nginx/html
COPY html/${RENK}/ .

HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
  CMD curl -f http://localhost/ || exit 1


CMD ["./script.sh"]
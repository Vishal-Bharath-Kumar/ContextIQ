# Custom local-dev Kafka image — apache/kafka + openssl/su-exec for SASL_SSL+SCRAM bootstrap.
#
# The upstream apache/kafka image ships without openssl, so we can't build the
# PKCS12 keystore/truststore or bootstrap SCRAM credentials using only its
# built-in `configure`/`run` scripts. This image adds the small set of tools
# needed and replaces the entrypoint with docker/kafka/entrypoint.sh.

FROM apache/kafka:3.8.0

USER root
RUN apk add --no-cache openssl bash su-exec

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]

#!/bin/sh
# Lego box: a wrapper for lego
# Lol

# set -a export ALL env vars in the lego-box-environment file
set -a && . /etc/lego-box-environment && set +a

if test -r "$ACME_SECRETS_ENV_FILE"; then
    echo "Dot-sourcing secrets file at '$ACME_SECRETS_ENV_FILE'"
    set -a && . "$ACME_SECRETS_ENV_FILE" && set +a
else
    echo "Secrets file at '$ACME_SECRETS_ENV_FILE' does not exist, nothing to dot-source"
fi

case "$ACME_SERVER" in
    staging) serverarg="--server 'https://acme-staging.api.letsencrypt.org/directory'" ;;
    production) serverarg="" ;;
    *) echo "Unknown value for ACME_SERVER '$ACME_SERVER'"; exit 1 ;;
esac

if test -e "${ACME_DIR}/certificates/${ACME_DOMAIN}.key"; then
    lego_action="renew"
else
    lego_action="run"
fi

invocation="lego --accept-tos --path '$ACME_DIR' --email '$ACME_LETSENCRYPT_EMAIL' --domains '$ACME_DOMAIN' --dns '$ACME_DNS_AUTHENTICATOR' $serverarg '$lego_action'"

printf 'Running lego... start time: ' | tee "$ACME_LOGFILE"
date '+%Y%m%d-%H%M%S' | tee "$ACME_LOGFILE"
echo "$invocation" | tee "$ACME_LOGFILE"
echo "With environment:" | tee "$ACME_LOGFILE"
env | sed 's/^/  /g' | tee "$ACME_LOGFILE"

chown -R "${ACME_USER}:${ACME_USER}" "$ACME_DIR"
if test "$1" != "--whatif"; then
    su "$ACME_USER" -c "$invocation" | tee "$ACME_LOGFILE"
fi

printf "\n> find $ACME_DIR:\n$(find "$ACME_DIR")\n\n"

printf 'Finished running lego... end time: ' | tee "$ACME_LOGFILE"
date '+%Y%m%d-%H%M%S' | tee "$ACME_LOGFILE"

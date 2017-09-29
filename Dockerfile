# xenolf/lego is based on alpine
FROM xenolf/lego:latest
LABEL maintainer "me@micahrl.com"

# An email address to send to Let's Encrypt
# You don't need to set up an account ahead of time; lego can do it for you
ENV ACME_LETSENCRYPT_EMAIL you@example.com

# The domain to create/renew the certificate for
ENV ACME_DOMAIN example.com

# The name of the DNS provider
ENV ACME_DNS_AUTHENTICATOR manual

# You also must pass variables for the API key of your DNS provider
# Run `lego dnshelp` for more information about each specific provider
# Note that these variables are not prefixed with "ACME_"

# Configure update frequency. Valid values are:
# - once:    Perform the task once and exit
# - monthly: Perform the task once, and run a cron daemon configured to
#            perform it again on the first of every month
# - devel:   *Never* perform the task, but run a cron job that executes every
#            *minute* that logs the command that *would* be run
ENV ACME_FREQUENCY devel

# Intended to enhance readability of my Dockerfile and scripts
# Not intended to change at runtime
ENV ACME_USER acme
ENV ACME_DIR /srv/inflatable-wharf

RUN /bin/true \

    # NOTE: the adduser call also creates $ACME_DIR with correct permissions
    && addgroup -S "$ACME_USER" \
    && adduser -S -G "$ACME_USER" -s /bin/sh -h "$ACME_DIR" "$ACME_USER" \

    && /bin/true

# NOTE: We do not use a USER statement, because crond (and therefore entrypoint.sh) must be run as root

COPY ["perforated-cardboard.sh", "/usr/local/bin/"]
ENTRYPOINT ["/bin/sh"]
CMD ["-c", "/usr/local/bin/perforated-cardboard.sh"]

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

# If this is "staging", use the staging server
# If it's any other value, use the production server
ENV ACME_SERVER staging

# You also must pass variables for your DNS provider credentials,
# such as an API access key and/or secret
# Run this command for more information about each specific provider:
#   docker run xenolf/lego:latest dnshelp
# Note that these variables are not prefixed with "ACME_"

# Instead of passing the API credentials directly,
# you may pass the location of a file on the filesystem containing them;
# that file will be dot-sourced before running lego
# This is intended to be used with Docker swarm secrets.
ENV ACME_SECRETS_ENV_FILE /var/inflatable-wharf/secrets

# Configure update frequency. Valid values are:
# - once:    Perform the task once and exit
# - monthly: Perform the task once, and run a cron daemon configured to
#            perform it again on the first of every month
# - devel:   *Never* perform the task, but run a cron job that executes every
#            *minute* that logs the command that *would* be run
ENV ACME_FREQUENCY devel

# All subsequent environment variables are intended to enhance readability
# *Not intended to change at runtime*

# This value cannot change because afaik the VOLUME will not change at runtime
ENV ACME_DIR /srv/inflatable-wharf

ENV ACME_USER acme
ENV ACME_LOGFILE "$ACME_DIR/acme.log"

# NOTE: adduser will set permissions on $ACME_DIR
# NOTE: We do not use a USER statement, because crond (and therefore entrypoint.sh) must be run as root
RUN /bin/true \
    && addgroup -S "$ACME_USER" \
    && adduser -S -G "$ACME_USER" -s /bin/sh -h "$ACME_DIR" "$ACME_USER" \
    && /bin/true

# REMINDER: Adjust permissions and set volume contents *before* declaring the volume
VOLUME $ACME_DIR

COPY ["perforated-cardboard.sh", "/usr/local/bin/"]
RUN chmod 755 /usr/local/bin/perforated-cardboard.sh

CMD ["/bin/sh", "-i"]
ENTRYPOINT ["/usr/local/bin/perforated-cardboard.sh"]

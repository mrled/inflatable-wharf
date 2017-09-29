#!/bin/sh
# Perforated cardboard is the. uhh. the entry point. For a box of Lego.

set -e
set -u

legoboxpath="/usr/local/bin/lego-box.sh"

# Write out legobox wrapper script
# We do this because we have the ACME_ environment variables in context here,
# but they will *not* be in context when run from crond
cat > "$legoboxpath" <<LEGOBOXEOF
#!/bin/sh
# Lego box: a wrapper for lego
# Lol

if test -e "${ACME_DIR}/certificates/${ACME_DOMAIN}.key"; then
    lego_action="renew"
else
    lego_action="run"
fi

invocation="lego --accept-tos --path \"$ACME_DIR\" --email \"$ACME_LETSENCRYPT_EMAIL\" --domains \"$ACME_DOMAIN\" --dns \"$ACME_DNS_AUTHENTICATOR\" \"\$lego_action\""
if test "\$1" == "--whatif"; then
    echo "\$invocation"
else
    \$invocation
fi
LEGOBOXEOF
chmod 755 "$legoboxpath"

cron01min='* * * * *'
cron30day='* * 1 * *'

# Configure the crontab based on the frequency given by the environment
# Note that when we do 'crontab -' below, this *replaces* the existing crontab
# for our user; good in case we 'docker run' the container more than once
runonce=1
case "$ACME_FREQUENCY" in
    monthly) crontab="$cron30day $legoboxpath" ;;
    devel) crontab="$cron01min $legoboxpath --whatif"; runonce= ;;
    once) crontab="" ;;
    *) echo "Unknown value for ACME_FREQUENCY '$ACME_FREQUENCY'"; exit 1;;
esac

# Show whatif at first
su -l "$ACME_USER" -c "$legoboxpath --whatif"

# Run once
test "$runonce" && su -l "$ACME_USER" -c "$legoboxpath"

if test "$crontab"; then
    echo "Setting crontab:"
    echo "$crontab"
    echo "$crontab" | crontab -u "$ACME_USER" -

    touch "$ACME_DIR/crond.log"
    # Set the cron daemon to run in the background
    crond -b -L "$ACME_DIR/crond.log"
    # Tail the cron log forever
    tail -f "$ACME_DIR/crond.log"
else
    # Just echo a message and exit
    echo "No crontab to set"
fi

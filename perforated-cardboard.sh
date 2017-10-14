#!/bin/sh
# Perforated cardboard is the. uhh. the entry point. For a box of Lego.
# Sorry

set -e
set -u

lego_box_env_file=/etc/lego-box-environment

echo "ENTRYPOINT Environment:"
env | sed 's/^/  /g'
printf "\n\n"

# Take in a line from `env`, like "ACME_WHATEVER=hahaha"
# If it starts with ACME_,
# or if it is found in the output of `lego dnshelp`,
# return true; otherwise return false.
dnshelp=$(lego dnshelp)
is_lego_dns_var() {
    varname="${1%%=*}"
    if echo "$varname" | grep -q '^ACME_'
    then
        return 0
    elif
        echo "$varname" | grep '[A-Z]' | grep '^\([A-Z]*_*\)*$' >/dev/null &&
        printf "$dnshelp" | grep -q "\b$varname\b"
    then
        return 0
    else
        return 1
    fi
}

# Save all relevant environment variables here,
# then read this file in the legobox script,
# because they aren't in scope when running that script from cron or su
echo "" > "$lego_box_env_file"
chmod 644 "$lego_box_env_file"
for envline in $(env); do
    if test "$envline" && is_lego_dns_var "$envline"; then
        echo "$envline" >> "$lego_box_env_file"
    fi
done

echo "Saved environment to '$lego_box_env_file':"
cat "$lego_box_env_file" | sed 's/^/  /g'

legoboxpath="/usr/local/bin/lego-box.sh"

# Write out legobox wrapper script
# We do this from a here-string
# (instead of just a spearate script that is COPY'd in the Dockerfile)
# because we have the ACME_ environment variables in context here
cat > "$legoboxpath" <<LEGOBOXEOF
#!/bin/sh
# Lego box: a wrapper for lego
# Lol

# set -a export ALL env vars in the lego-box-environment file
set -a && . "$lego_box_env_file" && set +a

if test -r "$ACME_SECRETS_ENV_FILE"; then
    echo "Dot-sourcing secrets file at '$ACME_SECRETS_ENV_FILE'"
    set -a && . "$ACME_SECRETS_ENV_FILE" && set +a
else
    echo "Secrets file at '$ACME_SECRETS_ENV_FILE' does not exist, nothing to dot-source"
fi

serverarg=
if test "$ACME_SERVER" = "staging"; then
    serverarg="--server 'https://acme-staging.api.letsencrypt.org/directory'"
fi

if test -e "${ACME_DIR}/certificates/${ACME_DOMAIN}.key"; then
    lego_action="renew"
else
    lego_action="run"
fi

invocation="lego --accept-tos --path '$ACME_DIR' --email '$ACME_LETSENCRYPT_EMAIL' --domains '$ACME_DOMAIN' --dns '$ACME_DNS_AUTHENTICATOR' \$serverarg \"\$lego_action\""

printf 'Running lego... start time: ' | tee '$ACME_LOGFILE'
date '+%Y%m%d-%H%M%S' | tee '$ACME_LOGFILE'
echo "\$invocation" | tee '$ACME_LOGFILE'
echo "With environment:" | tee '$ACME_LOGFILE'
env | sed 's/^/  /g' | tee '$ACME_LOGFILE'
if test "\$1" != "--whatif"; then
    sh -c "\$invocation" | tee '$ACME_LOGFILE'
fi
printf 'Finished running lego... end time: ' | tee '$ACME_LOGFILE'
date '+%Y%m%d-%H%M%S' | tee '$ACME_LOGFILE'
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

# Make sure logfile permissions are ok
touch "$ACME_LOGFILE"
chown "$ACME_USER:$ACME_USER" "$ACME_LOGFILE"

# Show whatif at first
su -l "$ACME_USER" -c "$legoboxpath --whatif"

# Run once
test "$runonce" && su -l "$ACME_USER" -c "$legoboxpath"

if test "$crontab"; then
    echo "Setting crontab:"
    echo "$crontab"
    echo "$crontab" | crontab -u "$ACME_USER" -

    # Set the cron daemon to run in the background
    crond -b # -L "$ACME_DIR/crond.log"
    # Tail the ACME logfile forever
    tail -f "$ACME_LOGFILE"
else
    # Just echo a message and exit
    echo "No crontab to set"
fi

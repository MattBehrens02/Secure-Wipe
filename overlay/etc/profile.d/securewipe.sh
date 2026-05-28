# Make the Secure-Wipe launcher available in interactive bash shells.
case "$-" in
    *i*)
    alias securewipe='/usr/local/bin/securewipe'
        ;;
esac

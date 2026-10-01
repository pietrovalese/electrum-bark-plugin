# electrum-bark-plugin

Plugin Electrum (Qt) per barkd. Struttura attesa:

    hackathon/
      electrum/  barkd/  electrum-bark-plugin/  venv/

## Sviluppo
    ln -s ~/hackathon/electrum-bark-plugin/bark ~/hackathon/electrum/electrum/plugins/bark
    cd ~/hackathon/electrum && ./run_electrum --signet
    # Tools -> Plugins -> Bark (abilita), poi Impostazioni: host/token oppure "client finto"
    # Se abiliti con un wallet già aperto, chiudilo e riaprilo.

## Test
    cd ~/hackathon/electrum-bark-plugin && python -m pytest tests

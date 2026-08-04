# Contract fixtures

`fire_lake.transect.json` is a committed sample of the data contract, used by
`test_contract_shape.py` to lock the fields the front end binds to. Regenerate it
after an intentional contract change:

    ssh root@<droplet> 'docker exec transect-api cat /app/outputs/fire_lake/transect.json' \
      > tests/fixtures/fire_lake.transect.json

It is a fixture, not truth — update it deliberately when the contract changes, and
the shape tests will tell you what moved.

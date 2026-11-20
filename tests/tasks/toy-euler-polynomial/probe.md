# Probe: toy-euler-polynomial

```
$ python3 checker.py probe/near_39.json
{"valid": false, "score": null, "reason": "39*39 + 39 + 41 = 1601 is prime"}
$ python3 checker.py probe/near_1001.json
{"valid": false, "score": null, "reason": "n must be a whole number from 0 to 1000"}
$ python3 checker.py probe/near_text.json
{"valid": false, "score": null, "reason": "n must be a whole number from 0 to 1000"}
$ python3 probe/variant_check.py checker.py probe/variant_n2.json
{"valid": true, "score": null, "reason": "variant n*n + 1: 10 = 2 * 5"}
$ python3 checker.py probe/near_extra_key.json
{"valid": false, "score": null, "reason": "the object must be {\"n\": n} and nothing else"}
```

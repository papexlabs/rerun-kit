# Probe: toy-pairs

```
$ python3 checker.py best_known.json
{"valid": true, "score": 10, "reason": "10 distinct numbers from 1 to 30, no two adding up to 31"}
$ python3 checker.py probe/v1_sum.json
{"valid": false, "score": null, "reason": "1 and 30 add up to 31"}
$ python3 checker.py probe/v2_range.json
{"valid": false, "score": null, "reason": "entry 0 is not a whole number from 1 to 30"}
$ python3 checker.py probe/v3_twice.json
{"valid": false, "score": null, "reason": "2 appears twice"}
$ python3 checker.py probe/v9_extra_key.json
{"valid": false, "score": null, "reason": "the object must be {\"numbers\": [...]} and nothing else"}
```

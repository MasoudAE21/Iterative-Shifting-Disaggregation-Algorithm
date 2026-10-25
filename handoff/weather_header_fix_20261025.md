# Weather header encoding fix

User validation found four failures from the same read_weather header check.
The expected Celsius headers in weather.py contained corrupted Unicode; both
the pipeline fixture and actual Open-Meteo input use the correct degree symbol.
Replaced the constants with explicit Unicode escapes for U+00B0. Strict column
order and unit validation remain intact; Fahrenheit is still rejected.

Added independent Celsius/Fahrenheit header regression tests and included them
in step 2 of VALIDATION_GUIDE.md. Six focused cases passed: the two header cases,
the pipeline fixture, and the three checkpoint failure cases. No full real-data
pipeline was run. git diff --check passed.

"""The six Sortyard services (design draft §4), each a console script of this package."""

SERVICES: dict[str, str] = {
    "api": "sortyard.services.api",
    "conductor": "sortyard.services.conductor",
    "context-assembler": "sortyard.services.context_assembler",
    "eval-runner": "sortyard.services.eval_runner",
    "sensor-runner": "sortyard.services.sensor_runner",
    "integrator": "sortyard.services.integrator",
}

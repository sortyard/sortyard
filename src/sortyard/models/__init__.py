"""The §3 domain objects as Python data models, generated from spec/*.schema.json.

``MODELS`` maps each schema file stem to its model; ``Model.from_dict`` / ``to_dict`` convert
between a model and the schema's JSON form. The classes live in ``_generated`` (produced by
``python -m sortyard.models.codegen``; never edited by hand), on the runtime in ``_runtime``.
"""

from sortyard.models._generated import *  # noqa: F403
from sortyard.models._runtime import UNSET as UNSET
from sortyard.models._runtime import Model as Model
from sortyard.models._runtime import ModelError as ModelError
from sortyard.models._runtime import Unset as Unset

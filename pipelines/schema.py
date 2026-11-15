"""Imports every model so that the metadata is complete for migrations, security setup and tests."""

import modules.datalab.models  # noqa: F401
import modules.graph.models  # noqa: F401
import modules.intelligence.models  # noqa: F401
import modules.logging.audit  # noqa: F401
import modules.markets.models  # noqa: F401
import modules.portfolio.models  # noqa: F401
import modules.quant.models  # noqa: F401
import pipelines.models  # noqa: F401
import security.models  # noqa: F401
from core.db import Base

metadata = Base.metadata

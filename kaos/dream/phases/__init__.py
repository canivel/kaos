"""Dream phases — each phase is a pure function over a (conn, context) pair.

Phases are composed by `DreamCycle.run()` in a fixed order. Each phase returns
a ``PhaseReport`` describing what it found and did so the narrative phase can
assemble a coherent digest.
"""

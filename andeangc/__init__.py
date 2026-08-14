"""Helper modules for building the Andean Glacierized Catchment (Andean-GC) dataset.

The processing and figure notebooks import from here, e.g.::

    from andeangc import config as cfg

    cfg.period_q          # any key in config.yml, as an attribute
    cfg.VERSION           # data/<version>, where this pipeline writes
    cfg.RESOURCES         # data/resources, the raw institutional records
    cfg.data_dir('era5')  # an external dataset directory under data_root
"""

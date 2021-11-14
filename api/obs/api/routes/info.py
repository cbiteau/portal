import logging

# from sqlalchemy import select

from obs.api.app import api

from sanic.response import json

log = logging.getLogger(__name__)

from obs.api import __version__ as version


@api.route("/info")
async def info(req):
    return json(
        {
            "version": version,
        }
    )

import logging
import re
from json import load as jsonload
from os.path import join, exists, isfile

from sqlalchemy import select, func
from sqlalchemy.orm import joinedload

from obs.api.db import Track, User, Comment, DuplicateTrackFileError
from obs.api.app import api, require_auth, read_api_key, json

from sanic.response import file_stream, empty
from sanic.exceptions import InvalidUsage, NotFound, Forbidden

log = logging.getLogger(__name__)


def normalize_user_agent(user_agent):
    if not user_agent:
        return None

    m = re.match(r"\bOBS\/[^\s]+", user_agent)
    return m[0] if m else None


async def _return_tracks(req, extend_query, limit, offset):
    if limit <= 0 or limit > 100:
        raise InvalidUsage("invalid limit")

    if offset < 0:
        raise InvalidUsage("offset must be positive")

    count_query = extend_query(
        select(func.count()).select_from(Track).join(Track.author)
    )
    track_count = await req.ctx.db.scalar(count_query)

    query = (
        extend_query(select(Track).options(joinedload(Track.author)))
        .limit(limit)
        .offset(offset)
        .order_by(Track.created_at.desc())
    )

    tracks = (await req.ctx.db.execute(query)).scalars()

    return json(
        {
            "trackCount": track_count,
            "tracks": list(
                map(
                    lambda t: t.to_dict(
                        for_user_id=req.ctx.user.id if req.ctx.user else None
                    ),
                    tracks,
                )
            ),
        },
    )


@api.get("/tracks")
async def get_tracks(req):
    limit = req.ctx.get_single_arg("limit", default=20, convert=int)
    offset = req.ctx.get_single_arg("offset", default=0, convert=int)
    # author = req.ctx.get_single_arg("author", default=None, convert=int)

    def extend_query(q):
        q = q.where(Track.public)

        # if author is not None:
        #     q = q.where(Track.author_id == author)

        return q

    return await _return_tracks(req, extend_query, limit, offset)


@api.get("/tracks/feed")
@require_auth
async def get_feed(req):
    limit = req.ctx.get_single_arg("limit", default=20, convert=int)
    offset = req.ctx.get_single_arg("offset", default=0, convert=int)

    def extend_query(q):
        return q.where(Track.author_id == req.ctx.user.id)

    return await _return_tracks(req, extend_query, limit, offset)


@api.post("/tracks")
@read_api_key
@require_auth
async def post_track(req):
    try:
        file = req.files["body"][0]
    except LookupError as e:
        raise InvalidUsage(
            'Track upload needs a single file in "body" multipart field'
        ) from e

    try:
        body = req.json["track"]
    except (LookupError, InvalidUsage):
        body = {}

    title = body.get("title")
    public = body.get("public")

    track = Track(
        title=title,
        customized_title=bool(title),
        author=req.ctx.user,
        public=public
        if public is not None
        else req.ctx.user.are_tracks_visible_for_all,
    )
    track.generate_slug()
    try:
        await track.prevent_duplicates(req.ctx.db, file.body)
    except DuplicateTrackFileError:
        raise InvalidUsage("Track file is not unique")

    track.uploaded_by_user_agent = normalize_user_agent(req.headers["user-agent"])
    track.original_file_name = file.name
    await track.write_to_original_file(req.app.config, file.body)
    track.queue_processing()
    track.auto_generate_title()

    req.ctx.db.add(track)
    await req.ctx.db.commit()

    return await get_track(req, track.slug)


async def _load_track(req, slug, raise_not_found=True):
    track = (
        await req.ctx.db.execute(
            select(Track)
            .where(Track.slug == slug)
            .options(joinedload(Track.author))
            .limit(1)
        )
    ).scalar()

    if raise_not_found and track is None:
        raise NotFound()

    if not track.is_visible_to(req.ctx.user):
        raise Forbidden()

    return track


@api.get("/tracks/<slug:str>")
async def get_track(req, slug: str):
    track = await _load_track(req, slug)
    return json(
        {"track": track.to_dict(for_user_id=req.ctx.user.id if req.ctx.user else None)},
    )


@api.delete("/tracks/<slug:str>")
@require_auth
async def delete_track(req, slug: str):
    track = await _load_track(req, slug)
    if not track.is_visible_to_private(req.ctx.user):
        raise Forbidden()

    await req.ctx.db.delete(track)
    await req.ctx.db.commit()

    return empty()


@api.get("/tracks/<slug:str>/data")
async def get_track_data(req, slug: str):
    track = await _load_track(req, slug)

    FILE_BY_KEY = {
        "measurements": "measurements.json",
        "overtakingEvents": "overtakingEvents.json",
        "track": "track.json",
        "trackRaw": "trackRaw.json",
    }

    result = {}

    for key, filename in FILE_BY_KEY.items():
        file_path = join(
            req.app.config.PROCESSING_OUTPUT_DIR, track.file_path, filename
        )
        if not exists(file_path) or not isfile(file_path):
            continue

        with open(file_path) as f:
            result[key] = jsonload(f)

    return json(
        result,
    )


@api.get("/tracks/<slug:str>/download/original.csv")
async def download_original_file(req, slug: str):
    track = await _load_track(req, slug)

    if not track.is_visible_to_private(req.ctx.user):
        raise Forbidden()

    return await file_stream(
        track.get_original_file_path(req.app.config),
        mime_type="text/csv",
        filename=f"{slug}.csv",
    )


@api.get("/tracks/<slug:str>/download/track.gpx")
async def download_track_gpx(req, slug: str):
    track = await _load_track(req, slug)

    if not track.is_visible_to(req.ctx.user):
        raise Forbidden()

    file_path = join(req.app.config.PROCESSING_OUTPUT_DIR, track.file_path, "track.gpx")
    if not exists(file_path) or not isfile(file_path):
        raise NotFound()

    return await file_stream(
        file_path,
        mime_type="application/gpx+xml",
        filename=f"{slug}.gpx",
    )


@api.put("/tracks/<slug:str>")
@require_auth
async def put_track(req, slug: str):
    track = await _load_track(req, slug)

    if track.author_id != req.ctx.user.id:
        raise Forbidden()

    try:
        body = req.json["track"]
    except BaseException:
        body = {}

    if "title" in body:
        track.title = (body["title"] or "").strip() or None
        track.customized_title = track.title is not None

    if "description" in body:
        track.description = (body["description"] or "").strip() or None

    process = False

    if "public" in body:
        public = bool(body["public"])
        process = process or (public != track.public)  # if changed
        track.public = public

    if "body" in req.files:
        try:
            file = req.files["body"][0]
        except LookupError as e:
            raise InvalidUsage(
                'Track upload needs a single file in "body" multipart field'
            ) from e

        await track.prevent_duplicates(req.ctx.db, file.body)
        track.uploaded_by_user_agent = normalize_user_agent(req.headers["user-agent"])
        track.original_file_name = file.name or (track.slug + ".csv")
        await track.write_to_original_file(req.app.config, file.body)
        process = True

    if process:
        track.queue_processing()

    track.auto_generate_title()
    await req.ctx.db.commit()

    track = await _load_track(req, track.slug)
    return json(
        {"track": track.to_dict(for_user_id=req.ctx.user.id)},
    )


@api.get("/tracks/<slug:str>/comments")
async def get_track_comments(req, slug: str):
    limit = req.ctx.get_single_arg("limit", default=20, convert=int)
    offset = req.ctx.get_single_arg("offset", default=0, convert=int)

    track = await _load_track(req, slug)

    comment_count = await req.ctx.db.scalar(
        select(func.count()).select_from(Comment).where(Comment.track_id == track.id)
    )

    query = (
        select(Comment)
        .options(joinedload(Comment.author))
        .where(Comment.track_id == track.id)
        .order_by(Comment.created_at.desc())
        .limit(limit)
        .offset(offset)
    )

    comments = (await req.ctx.db.execute(query)).scalars()

    return json(
        {
            "commentCount": comment_count,
            "comments": list(
                map(
                    lambda c: c.to_dict(
                        for_user_id=req.ctx.user.id if req.ctx.user else None
                    ),
                    comments,
                )
            ),
        },
    )


@api.post("/tracks/<slug:str>/comments")
@require_auth
async def post_track_comment(req, slug: str):
    track = await _load_track(req, slug)

    body = req.json.get("comment", {}).get("body")
    if not isinstance(body, str):
        raise InvalidUsage("no comment given")

    # Ensure body is not empty
    body = body.strip()
    if not body:
        raise InvalidUsage("empty comment")

    comment = Comment(
        body=body,
        track_id=track.id,
        author_id=req.ctx.user.id,
    )

    req.ctx.db.add(comment)
    await req.ctx.db.commit()

    await req.ctx.db.refresh(comment)

    comment = (
        await req.ctx.db.execute(
            select(Comment)
            .options(joinedload(Comment.author))
            .where(Comment.id == comment.id)
            .limit(1)
        )
    ).scalar()

    return json({"comment": comment.to_dict(for_user_id=req.ctx.user.id)})


@api.delete("/tracks/<slug:str>/comments/<uid:str>")
@require_auth
async def delete_track_comment(req, slug: str, uid: str):
    track = await _load_track(req, slug)

    comment = (
        await req.ctx.db.execute(
            select(Comment)
            .options(joinedload(Comment.author))
            .where(Comment.track_id == track.id and Comment.uid == uid)
            .limit(1)
        )
    ).scalar()

    if not comment:
        raise NotFound()

    if comment.author_id != req.ctx.user.id:
        raise Forbidden()

    await req.ctx.db.delete(comment)
    await req.ctx.db.commit()

    return empty()

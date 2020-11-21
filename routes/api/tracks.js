const router = require('express').Router();
const mongoose = require('mongoose');
const TrackData = mongoose.model('TrackData');
const Track = mongoose.model('Track');
const Comment = mongoose.model('Comment');
const User = mongoose.model('User');
const auth = require('../auth');
const currentTracks = new Map();
const TrackInfo = require('../../logic/TrackInfo');
const { addPointsToTrack } = require('../../logic/tracks');

const wrapRoute = (fn) => async (req, res, next) => {
  try {
    return await fn(req, res);
  } catch (err) {
    next(err);
  }
};

// Preload track objects on routes with ':track'
router.param('track', async (req, res, next, slug) => {
  try {
    const track = await Track.findOne({ slug }).populate('author');

    if (!track) {
      return res.sendStatus(404);
    }

    req.track = track;

    return next();
  } catch (err) {
    return next(err);
  }
});

router.param('comment', async (req, res, next, id) => {
  try {
    const comment = await Comment.findById(id);

    if (!comment) {
      return res.sendStatus(404);
    }

    req.comment = comment;

    return next();
  } catch (err) {
    return next(err);
  }
});

router.get(
  '/',
  auth.optional,
  wrapRoute(async (req, res) => {
    const query = {};
    let limit = 20;
    let offset = 0;

    if (typeof req.query.limit !== 'undefined') {
      limit = req.query.limit;
    }

    if (typeof req.query.offset !== 'undefined') {
      offset = req.query.offset;
    }

    if (typeof req.query.tag !== 'undefined') {
      query.tagList = { $in: [req.query.tag] };
    }

    const [author, favoriter] = await Promise.all([
      req.query.author ? User.findOne({ username: req.query.author }) : null,
      req.query.favorited ? User.findOne({ username: req.query.favorited }) : null,
    ]);

    if (author) {
      query.author = author._id;
    }

    if (favoriter) {
      query._id = { $in: favoriter.favorites };
    } else if (req.query.favorited) {
      query._id = { $in: [] };
    }

    const results = await Promise.all([
      Track.find(query)
        .limit(Number(limit))
        .skip(Number(offset))
        .sort({ createdAt: 'desc' })
        .populate('author')
        .where('visible')
        .equals(true)
        .exec(),
      Track.countDocuments(query).exec(),
      req.payload ? User.findById(req.payload.id) : null,
    ]);

    const [tracks, tracksCount, user] = results;

    return res.json({
      tracks: tracks.map((track) => track.toJSONFor(user)),
      tracksCount,
    });
  }),
);

router.get(
  '/feed',
  auth.required,
  wrapRoute(async (req, res) => {
    let limit = 20;
    let offset = 0;

    if (typeof req.query.limit !== 'undefined') {
      limit = req.query.limit;
    }

    if (typeof req.query.offset !== 'undefined') {
      offset = req.query.offset;
    }

    const user = await User.findById(req.payload.id);

    if (!user) {
      return res.sendStatus(401);
    }

    const showByUserIds = [req.payload.id, ...(user.following || [])];

    const [tracks, tracksCount] = await Promise.all([
      Track.find({ author: { $in: showByUserIds } })
        .limit(Number(limit))
        .skip(Number(offset))
        .populate('author')
        .exec(),
      Track.countDocuments({ author: { $in: showByUserIds } }),
    ]);

    return res.json({
      tracks: tracks.map(function (track) {
        return track.toJSONFor(user);
      }),
      tracksCount: tracksCount,
    });
  }),
);

router.post(
  '/',
  auth.required,
  wrapRoute(async (req, res) => {
    const user = await User.findById(req.payload.id);

    if (!user) {
      return res.sendStatus(401);
    }

    const track = new Track(req.body.track);
    const trackData = new TrackData();
    track.trackData = trackData._id;

    if (req.body.track.body && req.body.track.body.trim()) {
      trackData.points = [];
      addPointsToTrack({ trackData }, track.body);
    }

    track.author = user;
    track.visible = track.author.areTracksVisibleForAll;
    await trackData.save();

    await track.save();

    // console.log(track.author);
    return res.json({ track: track.toJSONFor(user) });
  }),
);

router.post(
  '/add',
  auth.optional,
  wrapRoute(async (req, res) => {
    // console.log("Add");

    // console.log(req.payload);
    const user = await User.findById(req.body.id);

    if (!user) {
      return res.sendStatus(401);
    }

    let ti = null;
    if (currentTracks.has(req.body.id)) ti = currentTracks.get(req.body.id);

    // console.log("TI" + ti);
    // console.log("TILen" + ti.trackData.points.length);
    // console.log("TITrack" + ti.track);
    // console.log("Body" + req.body.track.body);
    if (ti.track) {
      addPointsToTrack(ti, req.body.track.body);
      // console.log("TLen" + ti.trackData.points.length);
      ti.track.author = user;
    }

    // await track.save()
    // return res.json({ track: track.toJSONFor(user) });
    return res.sendStatus(200);
  }),
);

router.post(
  '/begin',
  auth.optional,
  wrapRoute(async (req, res) => {
    // console.log("Begin");
    // console.log(req.payload);
    const user = await User.findById(req.body.id);

    if (!user) {
      return res.sendStatus(401);
    }

    if (currentTracks.has(req.body.id)) currentTracks.delete(req.body.id); // delete old parts if there are leftovers
    const ti = new TrackInfo(new Track(req.body.track), new TrackData());
    ti.track.trackData = ti.trackData._id;
    currentTracks.set(req.body.id, ti);

    // console.log("addToTrack"+req.body);

    addPointsToTrack(ti, ti.track.body);

    // console.log("TLen" + ti.track);
    // console.log("TLen" + ti.trackData);
    // console.log("TLen" + ti.trackData.points.length);

    // console.log(track.trackData.points[0].date);
    ti.track.author = user;

    // await track.save()
    // console.log(track.author);
    return res.sendStatus(200);
  }),
);

router.post(
  '/end',
  auth.optional,
  wrapRoute(async (req, res) => {
    const user = await User.findById(req.body.id);
    if (!user) {
      return res.sendStatus(401);
    }

    let ti;
    if (currentTracks.has(req.body.id)) {
      ti = currentTracks.get(req.body.id);
      addPointsToTrack(ti, req.body.track.body);
    } else {
      ti = new TrackInfo(new Track(req.body.track), new TrackData());
      ti.track.trackData = ti.trackData._id;
      addPointsToTrack(ti, ti.track.body);
    }
    if (ti.track) {
      ti.track.author = user;
    }

    currentTracks.delete(req.body.id); // we are done with this track, it is complete
    ti.track.author = user;

    // console.log(track);
    // console.log("user:"+user);
    await ti.track.save();

    // console.log("TLen" + ti.track);
    // console.log("TLen" + ti.trackData);
    // console.log("TLen" + ti.trackData.points.length);
    await ti.trackData.save();

    return res.sendStatus(200);
  }),
);

// return a track
router.get(
  '/:track',
  auth.optional,
  wrapRoute(async (req, res) => {
    const [user] = await Promise.all([
      req.payload ? User.findById(req.payload.id) : null,
      req.track.populate('author').execPopulate(),
    ]);
    return res.json({ track: req.track.toJSONFor(user, { body: true }) });
  }),
);

// update track
router.put('/:track', auth.required, async function (req, res, next) {
  const user = await User.findById(req.payload.id);

  if (req.track.author._id.toString() !== req.payload.id.toString()) {
    return res.sendStatus(403);
  }

  if (typeof req.body.track.title !== 'undefined') {
    req.track.title = req.body.track.title;
  }

  if (typeof req.body.track.description !== 'undefined') {
    req.track.description = req.body.track.description;
  }

  if (req.body.track.body && req.body.track.body.trim()) {
    req.track.body = req.body.track.body.trim();

    let trackData = await TrackData.findById(req.track.trackData);
    if (!trackData) {
      trackData = new TrackData();
      req.track.trackData = trackData._id;
    }
    trackData.points = [];
    addPointsToTrack({ trackData }, req.track.body);
    await trackData.save();
  }

  if (typeof req.body.track.tagList !== 'undefined') {
    req.track.tagList = req.body.track.tagList;
  }
  req.track.visible = req.body.track.visible;

  const track = await req.track.save();
  return res.json({ track: track.toJSONFor(user) });
});

// delete track
router.delete(
  '/:track',
  auth.required,
  wrapRoute(async (req, res) => {
    const user = await User.findById(req.payload.id);
    if (!user) {
      return res.sendStatus(401);
    }
    if (req.track.author._id.toString() === req.payload.id.toString()) {
      await TrackData.findByIdAndDelete(req.track.trackData);
      await req.track.remove();
      return res.sendStatus(204);
    } else {
      return res.sendStatus(403);
    }
  }),
);

// Favorite an track
router.post(
  '/:track/favorite',
  auth.required,
  wrapRoute(async (req, res) => {
    const trackId = req.track._id;

    const user = await User.findById(req.payload.id);
    if (!user) {
      return res.sendStatus(401);
    }

    await user.favorite(trackId);
    const track = await req.track.updateFavoriteCount();
    return res.json({ track: track.toJSONFor(user) });
  }),
);

// Unfavorite an track
router.delete(
  '/:track/favorite',
  auth.required,
  wrapRoute(async (req, res) => {
    const trackId = req.track._id;

    const user = await User.findById(req.payload.id);
    if (!user) {
      return res.sendStatus(401);
    }

    await user.unfavorite(trackId);
    const track = await req.track.updateFavoriteCount();
    return res.json({ track: track.toJSONFor(user) });
  }),
);

// return an track's comments
router.get(
  '/:track/comments',
  auth.optional,
  wrapRoute(async (req, res) => {
    const user = await Promise.resolve(req.payload ? User.findById(req.payload.id) : null);

    await req.track
      .populate({
        path: 'comments',
        populate: {
          path: 'author',
        },
        options: {
          sort: {
            createdAt: 'desc',
          },
        },
      })
      .execPopulate();

    return res.json({
      comments: req.track.comments.map(function (comment) {
        return comment.toJSONFor(user);
      }),
    });
  }),
);

// create a new comment
router.post(
  '/:track/comments',
  auth.required,
  wrapRoute(async (req, res) => {
    const user = await User.findById(req.payload.id);
    if (!user) {
      return res.sendStatus(401);
    }

    const comment = new Comment(req.body.comment);
    comment.track = req.track;
    comment.author = user;

    await comment.save();

    req.track.comments.push(comment);

    await req.track.save();
    return res.json({ comment: comment.toJSONFor(user) });
  }),
);

router.delete(
  '/:track/comments/:comment',
  auth.required,
  wrapRoute(async (req, res) => {
    if (req.comment.author.toString() === req.payload.id.toString()) {
      req.track.comments.remove(req.comment._id);
      await req.track.save();
      await Comment.find({ _id: req.comment._id }).remove();
      res.sendStatus(204);
    } else {
      res.sendStatus(403);
    }
  }),
);

// return an track's trackData
router.get(
  '/:track/TrackData',
  auth.optional,
  wrapRoute(async (req, res) => {
    // console.log("requestTrackData"+req.track);
    const trackData = await TrackData.findById(req.track.trackData);
    // console.log({trackData: trackData});
    return res.json({ trackData: trackData });
  }),
);

module.exports = router;

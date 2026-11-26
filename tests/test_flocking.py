"""Tests for flocker.flocking: velocities from pitch positions, the measures of collective motion, and the nulls.

Project: Flocker
File: tests/test_flocking.py
Purpose: kinematics recovers known velocities and cuts tracks at gaps, jumps and spikes; the group measures give known
    answers for squares, common headings and clockwise and anticlockwise mills (in the video's left-handed frame);
    neighbours are ranked, aligned and placed correctly; the nulls keep what they promise to keep; on TeamTrack
    (integration), ids 0 and 13 are the goalkeepers, and the ground truth's 7 m jump is cut
Author: Paul Calnon
Created: 2026-11-25
License: CC0 1.0 (see LICENSE)
"""

import json

import numpy as np
import pandas as pd
import pytest

from flocker.cli import main
from flocker.flocking import FPS, GOALKEEPER_IDS, draw_clips, frame_measures, group_measures, kinematics, lagged_correlation, mix_clips, neighbour_pairs, players_from_gt, players_from_tracks, run_ids, shift_ids, shuffle_within
from flocker.mot import write_mot
from synthetic import write_teamtrack_sequence


def _track(pid, frames, x, y, team=0) -> pd.DataFrame:
    return pd.DataFrame({"frame": np.asarray(frames), "id": pid, "mx": np.asarray(x, float), "my": np.asarray(y, float), "team": team})


def _kin(rows) -> pd.DataFrame:
    """A kinematics()-like table from (frame, id, team, mx, my, vx, vy) tuples."""
    return pd.DataFrame(rows, columns=["frame", "id", "team", "mx", "my", "vx", "vy"])


@pytest.mark.unit
def test_kinematics_recovers_constant_and_accelerating_motion():
    f = np.arange(1, 61)
    t = (f - 1) / FPS
    k = kinematics(pd.concat([_track(3, f, 10 + 3.0 * t, -5 - 4.0 * t), _track(4, f, 2.0 * t**2, 0 * t)]))
    a, b = k[k["id"] == 3], k[k["id"] == 4]
    assert np.allclose(a["vx"], 3.0) and np.allclose(a["vy"], -4.0) and np.allclose(a["speed"], 5.0)
    assert np.allclose(a["sx"], a["mx"]) and np.allclose(a["sy"], a["my"])
    assert np.allclose(b["vx"], 4.0 * t)  # a quadratic filter differentiates a quadratic exactly, to the clip's ends
    assert (a["run"] == 0).all() and (b["run"] == 0).all()


@pytest.mark.unit
def test_kinematics_cuts_runs_at_gaps_jumps_and_short_runs():
    f = np.r_[np.arange(1, 41), np.arange(41, 81), np.arange(82, 92)]  # frame 81 is missing; frames 82-91 are a short run
    x = 0.1 * f
    x[40:] += 1.0  # a 1 m jump between frames 40 and 41; frames 80 and 82 are 0.2 m apart, so only the gap cuts there
    k = kinematics(_track(7, f, x, np.zeros(len(f)))).set_index("frame")
    assert k.loc[1:40, "run"].eq(0).all() and k.loc[41:80, "run"].eq(1).all() and k.loc[82:91, "run"].eq(2).all()
    assert np.allclose(k.loc[1:80, "vx"], 0.1 * FPS)  # neither run's velocity sees the jump
    assert k.loc[82:91, ["sx", "vx", "vy", "speed"]].isna().all().all()  # 10 frames: shorter than the 15-frame window


@pytest.mark.unit
def test_kinematics_drops_a_one_frame_spike_and_keeps_both_sides_clean():
    f = np.arange(1, 61)
    x = 0.05 * f
    x[19] += 1.0  # frame 20 is 1 m off
    k = kinematics(_track(1, f, x, np.zeros(60))).set_index("frame")
    assert np.isnan(k.loc[20, "vx"]) and k.loc[19, "run"] != k.loc[20, "run"] != k.loc[21, "run"]
    assert np.allclose(k.drop(20)["vx"], 0.05 * FPS)


@pytest.mark.unit
def test_kinematics_keeps_every_row_and_sorts_by_id_then_frame():
    f = np.arange(1, 31)
    df = pd.concat([_track(9, f, 0.1 * f, 0 * f), _track(2, f, 0 * f, -0.2 * f)]).sample(frac=1, random_state=0)
    k = kinematics(df)
    assert len(k) == 60 and k["id"].tolist() == [2] * 30 + [9] * 30 and k["frame"].tolist() == list(f) * 2
    assert np.allclose(k.loc[k["id"] == 2, "vy"], -0.2 * FPS) and np.allclose(k.loc[k["id"] == 9, "vx"], 0.1 * FPS)
    with pytest.raises(ValueError):
        kinematics(df, window=14)


@pytest.mark.unit
def test_run_ids_cut_at_missing_frames_long_steps_and_nan():
    assert run_ids([1, 2, 4, 5], [0, 0.1, 0.2, 0.3], [0, 0, 0, 0]).tolist() == [0, 0, 1, 1]
    assert run_ids([1, 2, 3], [0, 0.5, 0.6], [0, 0, 0], max_step=0.4).tolist() == [0, 1, 1]
    assert run_ids([1, 2, 3], [0, np.nan, 0.1], [0, 0, 0]).tolist() == [0, 1, 2]
    assert run_ids([], [], []).tolist() == []


@pytest.mark.unit
def test_group_measures_of_a_square():
    m = group_measures([(0, 0), (10, 0), (10, 10), (0, 10)])
    assert (m["n"], m["cx"], m["cy"], m["length"], m["width"]) == (4, 5.0, 5.0, 10.0, 10.0)
    assert m["hull_area"] == pytest.approx(100.0) and m["radius"] == pytest.approx(np.sqrt(50)) and m["nn_mean"] == pytest.approx(10.0)
    assert np.isnan(m["polarisation"]) and m["n_moving"] == 0


@pytest.mark.unit
def test_a_common_heading_is_polarised_and_does_not_mill():
    m = group_measures([(0, 0), (10, 0), (10, 10), (0, 10)], [(2, 1), (4, 2), (1, 0.5), (6, 3)])
    assert m["polarisation"] == pytest.approx(1.0) and m["polarisation_w"] == pytest.approx(1.0) and m["milling"] == pytest.approx(0.0, abs=1e-12)
    assert (m["vx"], m["vy"]) == pytest.approx((3.25, 1.625)) and m["n_moving"] == 4
    assert (m["hx"], m["hy"]) == pytest.approx((2 / np.sqrt(5), 1 / np.sqrt(5)))


@pytest.mark.unit
def test_milling_is_positive_for_a_clockwise_turn_in_the_video():
    # y runs down the video, so a turn from +x toward +y (increasing angle) is clockwise as seen in the video
    ang = np.linspace(0, 2 * np.pi, 12, endpoint=False)
    xy = 20 * np.column_stack([np.cos(ang), np.sin(ang)]) + (30, -10)
    tangent = 3 * np.column_stack([-np.sin(ang), np.cos(ang)])
    cw, acw = group_measures(xy, tangent), group_measures(xy, -tangent)
    assert cw["milling"] == pytest.approx(1.0) and acw["milling"] == pytest.approx(-1.0)
    assert cw["polarisation"] == pytest.approx(0.0, abs=1e-12) and cw["radius"] == pytest.approx(20.0)
    # the centroid is the whole group's: a standing player at (100, 0) moves it to (20, 0), off the movers' centre
    four = [(10, 0), (0, 10), (-10, 0), (0, -10)]
    m = group_measures(four + [(100, 0)], [(0, 1), (-1, 0), (0, -1), (1, 0), (0, 0)])
    assert m["n_moving"] == 4 and m["milling"] == pytest.approx(1 / np.sqrt(20))


@pytest.mark.unit
def test_slow_and_unmeasured_players_have_no_heading():
    xy = [(0, 0), (5, 0), (0, 5), (5, 5)]
    v = [(2, 0), (2, 0), (0, 0.3), (np.nan, np.nan)]  # the third is below 0.5 m/s, the fourth has no velocity
    m = group_measures(xy, v)
    assert (m["n"], m["n_moving"]) == (4, 2) and m["polarisation"] == pytest.approx(1.0)
    assert m["polarisation_w"] == pytest.approx(np.hypot(4, 0.3) / 4.3) and m["speed_mean"] == pytest.approx(4.3 / 3)
    assert (m["hx"], m["hy"]) == pytest.approx((1.0, 0.0))
    assert group_measures(xy, v, min_speed=0.2)["polarisation"] == pytest.approx(np.hypot(2, 1) / 3)


@pytest.mark.unit
def test_degenerate_groups_give_nan_or_zero_not_errors():
    one = group_measures([(1, 2)], [(1, 0)])
    assert one["n"] == 1 and one["radius"] == 0.0 and np.isnan(one["nn_mean"]) and np.isnan(one["hull_area"]) and np.isnan(one["polarisation"])
    assert np.isnan(one["polarisation_w"]) and (one["hx"], one["hy"]) == (1.0, 0.0)  # one mover: a heading, but no polarisation
    slow = group_measures([(0, 0), (5, 0)], [(0.1, 0), (np.nan, np.nan)])
    assert np.isnan(slow["polarisation_w"]) and np.isnan(slow["hx"])  # a single velocity, below the heading threshold
    line = group_measures([(0, 0), (1, 0), (5, 0)])  # collinear, at 2, 1 and 3 m from the centroid
    assert line["hull_area"] == 0.0 and line["radius"] == pytest.approx(np.sqrt(14 / 3)) and line["nn_mean"] == pytest.approx(2.0)
    assert group_measures([(0, 0), (1, 0)], [(1, 0), (-1, 0)])["polarisation"] == pytest.approx(0.0)
    empty = group_measures(np.zeros((0, 2)))
    assert empty["n"] == 0 and np.isnan(empty["radius"])


@pytest.mark.unit
def test_frame_measures_rows_per_group_and_opponent_distances():
    kin = _kin([(1, 1, 0, 0, 0, 1, 0), (1, 2, 0, 10, 0, 1, 0), (1, 3, 1, 0, 3, 0, 1), (1, 4, 1, 10, 4, 0, -1), (2, 1, 0, 0, 0, 1, 0), (2, 3, 1, 0, 3, 0, 1)])
    out = frame_measures(kin).set_index(["frame", "group"])
    assert list(out.index) == [(1, "0"), (1, "1"), (1, "both"), (2, "0"), (2, "1"), (2, "both")]
    assert out.loc[(1, "0"), "nn_opponent"] == pytest.approx(3.5) and out.loc[(1, "1"), "nn_opponent"] == pytest.approx(3.5)
    assert out.loc[(1, "0"), "polarisation"] == pytest.approx(1.0) and out.loc[(1, "1"), "polarisation"] == pytest.approx(0.0)
    assert out.loc[(1, "both"), "polarisation"] == pytest.approx(0.5) and out.loc[(1, "both"), "n"] == 4 and np.isnan(out.loc[(1, "both"), "nn_opponent"])
    assert out.loc[(2, "0"), "n"] == 1 and np.isnan(out.loc[(2, "0"), "polarisation"]) and out.loc[(2, "0"), "nn_opponent"] == pytest.approx(3.0)


@pytest.mark.unit
def test_neighbour_pairs_rank_distance_alignment_and_bearing():
    kin = _kin([(1, 1, 0, 0, 0, 2, 0), (1, 2, 0, 3, 0, 2, 0), (1, 3, 0, 0, 10, 0, 2), (1, 4, 0, 20, 0, 0.1, 0), (1, 5, 1, 0, -1, -2, 0)])
    p = neighbour_pairs(kin)
    a = p[p["id"] == 1].set_index(["relation", "rank"])
    assert a.loc[("teammate", 1), "other"] == 2 and a.loc[("teammate", 2), "other"] == 3 and a.loc[("teammate", 3), "other"] == 4
    assert a.loc[("teammate", 1), ["distance", "align", "bearing", "axis_x"]].tolist() == pytest.approx([3.0, 1.0, 1.0, 1.0])
    assert a.loc[("teammate", 2), ["distance", "align", "bearing", "axis_x"]].tolist() == pytest.approx([10.0, 0.0, 0.0, 0.0])
    assert np.isnan(a.loc[("teammate", 3), "align"])  # player 4 is too slow to have a heading
    assert a.loc[("opponent", 1), ["other", "distance", "align", "bearing", "axis_x"]].tolist() == pytest.approx([5, 1.0, -1.0, 0.0, 0.0])
    assert 4 not in set(p["id"])  # a player without a heading has no neighbours of their own
    assert len(p[p["id"] == 5]) == 4 and p.loc[p["id"] == 5, "relation"].eq("opponent").all()


@pytest.mark.unit
def test_shift_ids_moves_each_track_circularly_and_keeps_rows_whole():
    f = np.arange(1, 101)
    df = pd.concat([pd.DataFrame({"frame": f, "id": i, "orig": f, "vx": i * 1000.0 + f}) for i in (1, 2, 3)], ignore_index=True)
    out = shift_ids(df, np.random.default_rng(0), 100, 20)
    shifts = {}
    for i, g in out.groupby("id"):
        s = (g["frame"] - g["orig"]) % 100
        assert s.nunique() == 1 and 20 <= s.iloc[0] <= 80
        assert sorted(g["frame"]) == list(f) and np.allclose(g["vx"], i * 1000.0 + g["orig"])
        shifts[i] = s.iloc[0]
    assert len(set(shifts.values())) > 1
    same = shift_ids(df, np.random.default_rng(1), 100, 20, same=True)
    assert ((same["frame"] - same["orig"]) % 100).nunique() == 1
    one = shift_ids(df, np.random.default_rng(2), 100, 20, ids=[2])
    assert (one.loc[one["id"] != 2, "frame"] == one.loc[one["id"] != 2, "orig"]).all() and (one.loc[one["id"] == 2, "frame"] != one.loc[one["id"] == 2, "orig"]).all()
    with pytest.raises(ValueError):
        shift_ids(df, np.random.default_rng(0), 100, 51)


@pytest.mark.unit
def test_shuffle_within_permutes_velocities_inside_each_frame_and_team_only():
    rng = np.random.default_rng(3)
    df = pd.DataFrame([(f, i, i // 5, *rng.normal(size=2)) for f in range(1, 31) for i in range(10)], columns=["frame", "id", "team", "vx", "vy"])
    df.loc[7, ["vx", "vy"]] = np.nan
    df["speed"] = np.hypot(df["vx"], df["vy"])
    out = shuffle_within(df, np.random.default_rng(4))
    assert np.allclose(out["speed"], np.hypot(out["vx"], out["vy"]), equal_nan=True)  # speed moves with its velocity
    assert out[["frame", "id", "team"]].equals(df[["frame", "id", "team"]]) and out.loc[7, ["vx", "vy"]].isna().all()
    for _, g in df.groupby(["frame", "team"]):
        before = sorted(map(tuple, g[["vx", "vy"]].dropna().to_numpy()))
        after = sorted(map(tuple, out.loc[g.index, ["vx", "vy"]].dropna().to_numpy()))
        assert before == after  # the same (vx, vy) pairs, still paired, in the same frame and team
    assert (out["vx"] != df["vx"]).sum() > 100


@pytest.mark.unit
def test_mix_clips_takes_each_id_from_the_clip_its_plan_names():
    clips = {name: pd.DataFrame({"frame": np.tile([1, 2], 3), "id": np.repeat([1, 2, 3], 2), "src": name}) for name in ("a", "b", "c", "d")}
    out = mix_clips(clips, {1: "b", 2: "d", 3: "a"})
    assert len(out) == 6 and out.groupby("id")["src"].agg(set).to_dict() == {1: {"b"}, 2: {"d"}, 3: {"a"}}
    rng = np.random.default_rng(0)
    for _ in range(20):
        drawn = draw_clips(list(clips), 3, rng, exclude=["a"])
        assert len(set(drawn)) == 3 and "a" not in drawn
    assert len({tuple(draw_clips(list(clips), 2, rng)) for _ in range(30)}) > 3  # random, not a fixed order
    with pytest.raises(ValueError):
        draw_clips(list(clips), 4, rng, exclude=["a"])


@pytest.mark.unit
def test_lagged_correlation_peaks_where_b_follows_a():
    a = np.random.default_rng(5).normal(size=400)
    b = np.r_[np.full(7, np.nan), a[:-7]]  # b(t) = a(t - 7): b follows a by 7 samples
    lags = np.arange(-20, 21)
    c = lagged_correlation(a, b, lags)
    assert lags[np.nanargmax(c)] == 7 and c[lags == 7][0] == pytest.approx(1.0)
    assert abs(c[lags == -7][0]) < 0.2 and np.isnan(lagged_correlation(a[:2], b[:2], [0])[0])


@pytest.mark.unit
def test_players_from_gt_and_from_tracks_keep_outfield_players_only():
    gt = pd.DataFrame({"frame": 1, "id": [0, 1, 13, 14, 22], "cls": [0, 0, 0, 0, 1]})
    assert players_from_gt(gt)["id"].tolist() == [1, 14] and GOALKEEPER_IDS == (0, 13)
    tracks = pd.DataFrame({"frame": 1, "id": [1, 2, 3, 4, 5, 6], "cls": [0, 0, 0, 0, 1, -1]})
    teams = pd.DataFrame({"id": [1, 2, 3, 5, 6], "team": [0, 1, -1, 0, 1]})
    out = players_from_tracks(tracks, teams)
    assert out["id"].tolist() == [1, 2, 6] and out["team"].tolist() == [0, 1, 1]  # class -1: a tracker without classes


def _synthetic_match(tmp_path, n_frames=40, extra=21):
    """A TeamTrack-shaped tree: test clip D_20220220_1_1530_1560, whose team 0 (ids 1-10) circles clockwise in the
    video about (1000, 500) px at 3 px per frame, whose team 1 (ids 12-21) runs left at 1 px per frame on y = 900, and
    whose goalkeepers (0, 13) and ball (22) stand still; plus ``extra`` train clips like it, clip k's teams 20 k px
    lower, as sources for --null mix; and a pitch table for each that maps 10 px to 1 m in every frame."""
    names = ["D_20220220_1_1530_1560"] + [f"synthetic_{k:02d}" for k in range(1, extra + 1)]
    h = np.array([[0.1, 0, -192.0], [0, 0.1, -108.0], [0, 0, 1]]).ravel()
    (tmp_path / "pitch").mkdir()
    for k, name in enumerate(names):
        rows = []
        for f in range(1, n_frames + 1):
            for i in range(23):
                if 1 <= i <= 10:
                    a = 2 * np.pi * (i - 1) / 10 + 0.03 * f  # increasing angle with y down: clockwise in the video
                    x, y = 1000 + 100 * np.cos(a), 500 + 100 * np.sin(a)
                elif 11 <= i <= 21 and i != 13:
                    x, y = 300 + 150 * (i - 11) - f, 900
                else:
                    x, y = 200 + 50 * i, 1500
                rows.append((f, i, round(x) - 10, round(y) + 20 * k - 10, 20, 20))
        gt = pd.DataFrame(rows, columns=["frame", "id", "x", "y", "w", "h"])
        write_teamtrack_sequence(tmp_path / "tt", "test" if k == 0 else "train", name, gt, n_frames)
        pd.DataFrame([{"frame": f, **{f"h{j}": h[j] for j in range(9)}} for f in range(1, n_frames + 1)]).to_csv(tmp_path / "pitch" / f"{name}.csv", index=False)
        if k == 0:
            target = gt
    return names[0], target


@pytest.mark.unit
def test_flock_command_measures_ground_truth_tracks_and_nulls(tmp_path):
    name, gt = _synthetic_match(tmp_path)
    base = ["flock", "--teamtrack-root", str(tmp_path / "tt"), "--split", "test", "--pitch-dir", str(tmp_path / "pitch")]

    def run(out, *more):
        assert main(base + ["--out-dir", str(tmp_path / out), *more]) == 0
        return pd.read_csv(tmp_path / out / "frames.csv", dtype={"group": str}).set_index(["frame", "group"])

    t = run("gt")
    team0, team1 = t.xs("0", level="group"), t.xs("1", level="group")
    assert len(t) == 120 and (t["sequence"] == name).all() and set(t["sequence"]) == {name}  # only the test clip
    assert team0["n"].eq(10).all() and team1["n"].eq(10).all() and t.xs("both", level="group")["n"].eq(20).all()  # no goalkeepers, no ball
    assert (team0["milling"] > 0.95).all() and np.allclose(team1["hx"], -1.0) and np.allclose(team1["speed_mean"], 0.1 * FPS) and team1["width"].eq(0).all()
    assert json.loads((tmp_path / "gt" / "run.json").read_text())["settings"]["source"] == "ground truth"
    shuffled = run("shuffle", "--null", "shuffle", "--seed", "1").xs("0", level="group")
    assert np.allclose(shuffled["polarisation"], team0["polarisation"]) and shuffled["milling"].mean() < 0.5  # same headings, dealt at random
    mixed = run("mix", "--null", "mix", "--seed", "2")
    m0, m1 = mixed.xs("0", level="group"), mixed.xs("1", level="group")
    assert m1["n"].eq(10).all() and (m1["width"] > 1.5).all()  # team 1's players come from ten clips at different heights
    assert (m0["radius"] > 10.5).all() and json.loads((tmp_path / "mix" / "run.json").read_text())["settings"]["mix_pool"] == 22
    tracks = gt[~gt["id"].isin([0, 22])].assign(id=lambda d: d["id"] + 100, cls=0)  # track ids 101-121; 113 is the keeper
    write_mot(tracks, tmp_path / "tracks" / f"{name}.txt")
    (tmp_path / "tracks" / "teams").mkdir()
    pd.DataFrame({"id": range(101, 122), "team": [-1 if i in (105, 113) else 0 if i < 111 else 1 for i in range(101, 122)]}).to_csv(tmp_path / "tracks" / "teams" / f"{name}.csv", index=False)
    u = run("tr", "--tracks-dir", str(tmp_path / "tracks"))
    assert u.xs("0", level="group")["n"].eq(9).all() and u.xs("1", level="group")["n"].eq(10).all()  # track 105 is unlabelled
    for bad in (["--sequences", "no_such_clip"], ["--window", "14"], ["--null", "mix", "--tracks-dir", str(tmp_path / "tracks")]):
        assert main(base + ["--out-dir", str(tmp_path / "bad"), *bad]) == 2


@pytest.mark.integration
def test_ids_0_and_13_are_the_goalkeepers_and_the_7_m_jump_is_cut(real_teamtrack):
    """Team 0 defends the goal on the left of the video, team 1 the right, all match (one period). Measured in image
    pixels (the drone turns by at most 5 degrees), so this needs no homographies."""
    from flocker.mot import centers
    from flocker.teamtrack import find_sequence, list_sequences, load_gt
    from flocker.yolo_dataset import MISALIGNED_TRAIN

    for seq in list_sequences(real_teamtrack):
        gt = load_gt(seq, objects="players")
        gt["cx"] = centers(gt)[:, 0]
        left = gt[gt["team"] == 0].groupby("frame")["cx"].idxmin()
        right = gt[gt["team"] == 1].groupby("frame")["cx"].idxmax()
        share0, share13 = (gt.loc[left, "id"] == 0).mean(), (gt.loc[right, "id"] == 13).mean()
        if seq.name in ("D_20220220_1_0570_0600", "D_20220220_1_0600_0630"):  # two of the drifting clips: ids 0 and 13 play in midfield
            assert share0 < 0.05 and share13 < 0.05, seq.name
        else:
            assert share0 > 0.25 and share13 > 0.8, (seq.name, share0, share13)
    assert {"D_20220220_1_0570_0600", "D_20220220_1_0600_0630"} <= set(MISALIGNED_TRAIN)  # so the analysis never uses them
    gt = load_gt(find_sequence("D_20220220_1_0180_0210", real_teamtrack), objects="players")
    c = centers(gt) / 27.9  # metres, roughly: no homography needed to see a 7 m jump
    k = kinematics(gt.assign(mx=c[:, 0], my=c[:, 1])).set_index(["id", "frame"])
    assert k.loc[(0, 301), "run"] != k.loc[(0, 300), "run"] and k["speed"].max() < 12.5

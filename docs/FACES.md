# Faces

## How it works

1. **YuNet** finds faces in the snapshot (only when the object detector saw a `person`).
2. **SFace** aligns each face and turns it into an embedding of 128 numbers.
3. **FaceDB** (`data/faces.npz`) compares the embedding to the stored samples by cosine
   similarity. The best match at or above `ROBOT_FACE_THRESHOLD` (default 0.363, SFace's
   recommended value) is the person's name; otherwise it's an "unknown person".

There's no training step in the deep-learning sense. "Teaching" a face means storing a few
embeddings. That's fast enough to do on the Pi, and you can delete a person instantly.

## Enrolling

From the webcam (stop `make run` first, since Motion holds the camera):

```sh
make enroll-cam NAME=Stjepan
```

It takes 8 samples. Turn your head slightly and vary the distance between samples.

From photos (put them in `data/` first):

```sh
make enroll NAME=Ana IMGS="data/ana1.jpg data/ana2.jpg data/ana3.jpg"
```

The largest face in each photo is used. Photos are only read, never copied anywhere.

Check and remove people:

```sh
make faces
docker run --rm -v $PWD/data:/data robot:dev faces --forget Ana
```

## Getting good results

- Enroll **under the lighting and camera angle the robot will actually have**. Samples
  from the same webcam work better than phone photos.
- 5–10 samples per person is the sweet spot.
- If strangers get recognized as someone, raise the threshold (e.g. 0.42). If you're
  often "unknown", add more samples before lowering it.
- Faces smaller than about 40 px (far from a 640×480 camera) won't be detected reliably.

## Privacy

- Photos and video **never leave the device**. Claude only gets text like
  `face: recognized as Ana (similarity 0.64), center, close`.
- `data/faces.npz` holds embeddings, not pictures. You can't view them as photos, but
  they *are* biometric data: treat the file as private, don't commit it (it's in
  `.gitignore`), and delete people who ask.
- Motion's snapshots are deleted right after processing unless `ROBOT_KEEP_SNAPSHOTS=1`.
- Only enroll people who agreed to it. It's polite (and in the EU, GDPR-relevant once you
  go beyond your own household) to let visitors know there's a camera that recognizes faces.

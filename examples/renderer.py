import taichi_lang as ti
import numpy as np
import cv2
import math
import random

res = 512
num_spheres = 128
color_buffer = ti.Vector(3, dt=ti.f32)
sphere_pos = ti.Vector(3, dt=ti.f32)
inf = 1e10

# ti.runtime.print_preprocessed = True
# ti.cfg.print_ir = True
grid_resolution = 10
eps = 1e-4

@ti.layout
def buffers():
  ti.root.dense(ti.ij, res).place(color_buffer)
  ti.root.dense(ti.i, num_spheres).place(sphere_pos)

@ti.func
def query_density_int(ipos):
  # return ipos[0] + ipos[1] + ipos[2] < 16 and ipos.min() >= 0 or ipos.min() == 6 and ipos.max() == 9
  return ipos.min() % 3 == 0 and ipos.max() < 16


@ti.func
def dda(pos, d):
  rinv = 1.0 / d
  rsign = ti.Vector([0, 0, 0])
  for i in ti.static(range(3)):
    if d[i] > 0:
      rsign[i] = 1
    else:
      rsign[i] = -1

  o = grid_resolution * pos
  ipos = ti.Matrix.floor(o).cast(ti.i32)
  dis = (ipos - o + 0.5 + rsign * 0.5) * rinv
  running = 1
  i = 0
  hit_distance = -1.0
  normal = ti.Vector([0.0, 0.0, 0.0])
  hit_pos = ti.Vector([0.0, 0.0, 0.0])
  while running:
    last_sample = query_density_int(ipos)
    if last_sample:
      mini = (ipos - o + ti.Vector([0.5, 0.5, 0.5]) - rsign * 0.5) * rinv
      hit_distance = mini.max() * (1 / grid_resolution)
      hit_pos = pos + hit_distance * d
      running = 0
    else:
      mm = ti.Vector([0, 0, 0])
      if dis[0] <= dis[1] and dis[0] < dis[2]:
        mm[0] = 1
      elif dis[1] <= dis[0] and dis[1] <= dis[2]:
        mm[1] = 1
      else:
        mm[2] = 1
      dis += mm * rsign * rinv
      ipos += mm * rsign
      normal = -mm * rsign
    i += 1
    if i > grid_resolution * 10:
      running = 0
      normal = [0, 0, 0]
  return normal, hit_pos

# (T + x d)(T + x d) = r * r
# T*T + 2Td x + x^2 = r * r
# x^2 + 2Td x + (T * T - r * r) = 0

@ti.func
def intersect_sphere(pos, d, center):
  radius = 0.1
  T = pos - center
  A = 1
  B = 2 * T.dot(d)
  C = T.dot(T) - radius * radius
  delta = B * B - 4 * A * C
  dist = inf

  if delta > 0:
    sdelta = ti.sqrt(delta)
    ratio = 0.5 / A
    ret1 = ratio * (-B - sdelta)
    if ret1 > eps:
      dist = ret1
    else:
      ret2 = ratio * (-B + sdelta)
      if ret2 > eps:
        dist = ret2
  return dist


@ti.func
def intersect_spheres(pos, d):
  normal = ti.Vector([0.0, 0.0, 0.0])
  hit_pos = ti.Vector([0.0, 0.0, 0.0])
  min_dist = inf
  sid = -1

  for i in range(num_spheres):
    dist = intersect_sphere(pos, d, sphere_pos[i])
    if dist < min_dist:
      min_dist = dist
      sid = i

  if min_dist < inf:
    hit_pos = pos + d * min_dist
    normal = ti.Matrix.normalized(hit_pos - sphere_pos[sid])

  return normal, hit_pos


@ti.func
def next_hit(pos, d):
  # return dda(pos, d)
  return intersect_spheres(pos, d)

@ti.func
def out_dir(n):
  u = ti.Vector([1.0, 0.0, 0.0])
  if ti.abs(n[1]) < 1 - 1e-3:
    u = ti.Matrix.normalized(ti.Matrix.cross(n, ti.Vector([0.0, 1.0, 0.0])))
  v = ti.Matrix.cross(n, u)
  phi = 2 * math.pi * ti.random(ti.f32)
  ay = ti.random(ti.f32)
  ax = ti.sqrt(1 - ay * ay)
  return ax * (ti.cos(phi) * u + ti.sin(phi) * v) + ay * n


@ti.func
def color(pos):
  p = pos * grid_resolution

  p -= ti.Matrix.floor(p)
  boundary = 0.05
  count = 0
  for i in ti.static(range(3)):
    if p[i] < boundary or p[i] > 1 - boundary:
      count += 1
  f = 0.0
  if count >= 2:
    f = 1.0
  return ti.Vector([0.3, 0.4, 0.3]) * (1 + f)


@ti.kernel
def render():
  for u, v in color_buffer(0):
    fov = 0.6
    pos = ti.Vector([0.5, 0.5, 3.0])
    d = ti.Vector([fov * (u + ti.random(ti.f32)) / (res / 2) - fov - 1e-3,
                   fov * (v + ti.random(ti.f32)) / (res / 2) - fov - 1e-3,
                   -1.0])

    d = ti.Matrix.normalized(d)
    normal, hit_pos = next_hit(pos, d)

    contrib = ti.Vector([0.01, 0.013, 0.01])

    if normal.norm() != 0:
      c = color(hit_pos)

      d = out_dir(normal)
      # d = ti.Vector.normalized(ti.Vector([0.1, 0.5, -0.2]))
      normal, _ = next_hit(hit_pos + d * 1e-4, ti.Matrix.normalized(d))
      if normal.norm() == 0:
        contrib += c * ti.max(d[1], 0)
    else:
      contrib = ti.Vector([1, 1, 1])

    color_buffer[u, v] += contrib


@ti.kernel
def copy(img: np.ndarray):
  for i, j in color_buffer(0):
    coord = ((res - 1 - j) * res + i) * 3
    for c in ti.static(range(3)):
      img[coord + c] = color_buffer[i, j][2 - c]


def main():

  for i in range(num_spheres):
    for c in range(3):
      sphere_pos[i][c] = random.random()

  for i in range(1000):
    render()
    img = np.zeros((res * res * 3,), dtype=np.float32)
    copy(img)
    img = img.reshape(res, res, 3) * (1 / (i + 1))
    img = np.sqrt(img) * 2
    cv2.imshow('img', img)
    cv2.waitKey(1)
  cv2.waitKey(0)


if __name__ == '__main__':
  main()

#!/usr/bin/env python
#-*- coding: UTF-8 -*-

""" This program demonstrate the use of pyassimp to render
objects in OpenGL.

It loads a 3D model with ASSIMP and display it.

Materials are supported but textures are currently ignored.

Half-working keyboard + mouse navigation is supported.

This sample is based on several sources, including:
 - http://www.lighthouse3d.com/tutorials
 - http://www.songho.ca/opengl/gl_transform.html
 - http://code.activestate.com/recipes/325391/
 - ASSIMP's C++ SimpleOpenGL viewer
"""

import os, sys
from OpenGL.GLUT import *
from OpenGL.GLU import *
from OpenGL.GL import *
from OpenGL.arrays import ArrayDatatype

import logging;logger = logging.getLogger("assimp_opengl")
logging.basicConfig(level=logging.INFO)

import math
import numpy

from pyassimp import core as pyassimp
from pyassimp.postprocess import *
from pyassimp.helper import *


name = 'pyassimp OpenGL viewer'
height = 600
width = 900

class GLRenderer():
    def __init__(self):
        self.scene = None

        self.drot = 0.0
        self.dp = 0.0

        self.angle = 0.0
        self.x = 1.0
        self.z = 3.0
        self.lx = 0.0
        self.lz = 0.0
        self.using_fixed_cam = False
        self.current_cam_index = 0

        self.x_origin = -1 # x position of the mouse when pressing left btn

        # for FPS calculation
        self.prev_time = 0
        self.prev_fps_time = 0
        self.frames = 0

    def prepare_gl_buffers(self, mesh):

        mesh.gl = {}

        # Fill the buffer for vertex positions
        mesh.gl["vertices"] = glGenBuffers(1)
        glBindBuffer(GL_ARRAY_BUFFER, mesh.gl["vertices"])
        glBufferData(GL_ARRAY_BUFFER, 
                    mesh.vertices,
                    GL_STATIC_DRAW)

        # Fill the buffer for normals
        mesh.gl["normals"] = glGenBuffers(1)
        glBindBuffer(GL_ARRAY_BUFFER, mesh.gl["normals"])
        glBufferData(GL_ARRAY_BUFFER, 
                    mesh.normals,
                    GL_STATIC_DRAW)


        # Fill the buffer for vertex positions
        mesh.gl["triangles"] = glGenBuffers(1)
        glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, mesh.gl["triangles"])
        glBufferData(GL_ELEMENT_ARRAY_BUFFER, 
                    mesh.faces,
                    GL_STATIC_DRAW)

        # Unbind buffers
        glBindBuffer(GL_ARRAY_BUFFER,0)
        glBindBuffer(GL_ELEMENT_ARRAY_BUFFER,0)

    
    def load_dae(self, path, postprocess = None):
        logger.info("Loading model:" + path + "...")

        if postprocess:
            self.scene = pyassimp.load(path, postprocess)
        else:
            self.scene = pyassimp.load(path)
        logger.info("Done.")

        scene = self.scene
        #log some statistics
        logger.info("  meshes: %d" % len(scene.meshes))
        logger.info("  total faces: %d" % sum([len(mesh.faces) for mesh in scene.meshes]))
        logger.info("  materials: %d" % len(scene.materials))
        self.bb_min, self.bb_max = get_bounding_box(self.scene)
        logger.info("  bounding box:" + str(self.bb_min) + " - " + str(self.bb_max))

        self.scene_center = [(a + b) / 2. for a, b in zip(self.bb_min, self.bb_max)]

        for index, mesh in enumerate(scene.meshes):
            self.prepare_gl_buffers(mesh)

        # Finally release the model
        pyassimp.release(scene)

    def cycle_cameras(self):
        self.current_cam_index
        if not self.scene.cameras:
            return None
        self.current_cam_index = (self.current_cam_index + 1) % len(self.scene.cameras)
        cam = self.scene.cameras[self.current_cam_index]
        logger.info("Switched to camera " + str(cam))
        return cam

    def set_default_camera(self):

        if not self.using_fixed_cam:
            glLoadIdentity()
            gluLookAt(self.x ,1., self.z, # pos
                    self.x + self.lx - 1.0, 1., self.z + self.lz - 3.0, # look at
                    0.,1.,0.) # up vector


    def set_camera(self, camera):

        if not camera:
            return

        self.using_fixed_cam = True

        znear = camera.clipplanenear
        zfar = camera.clipplanefar
        aspect = camera.aspect
        fov = camera.horizontalfov

        glMatrixMode(GL_PROJECTION)
        glLoadIdentity()

        # Compute gl frustrum
        tangent = math.tan(fov/2.)
        h = znear * tangent
        w = h * aspect

        # params: left, right, bottom, top, near, far
        glFrustum(-w, w, -h, h, znear, zfar)
        # equivalent to:
        #gluPerspective(fov * 180/math.pi, aspect, znear, zfar)

        glMatrixMode(GL_MODELVIEW)
        glLoadIdentity()

        cam = transform(camera.position, camera.transformation)
        at = transform(camera.lookat, camera.transformation)
        gluLookAt(cam[0], cam[2], -cam[1],
                   at[0],  at[2],  -at[1],
                       0,      1,       0)

    def fit_scene(self, restore = False):
        """ Compute a scale factor and a translation to fit and center 
        the whole geometry on the screen.
        """

        x_max = self.bb_max[0] - self.bb_min[0]
        y_max = self.bb_max[1] - self.bb_min[1]
        tmp = max(x_max, y_max)
        z_max = self.bb_max[2] - self.bb_min[2]
        tmp = max(z_max, tmp)
        
        if not restore:
            tmp = 1. / tmp

        logger.info("Scaling the scene by %.03f" % tmp)
        glScalef(tmp, tmp, tmp)
    
        # center the model
        direction = -1 if not restore else 1
        glTranslatef( direction * self.scene_center[0], 
                      direction * self.scene_center[1], 
                      direction * self.scene_center[2] )

        return x_max, y_max, z_max
 
    def apply_material(self, mat):
        """ Apply an OpenGL, using one OpenGL list per material to cache 
        the operation.
        """

        if not hasattr(mat, "gl_mat"): # evaluate once the mat properties, and cache the values in a glDisplayList.
    
            diffuse = mat.properties.get("$clr.diffuse", numpy.array([0.8, 0.8, 0.8, 1.0]))
            specular = mat.properties.get("$clr.specular", numpy.array([0., 0., 0., 1.0]))
            ambient = mat.properties.get("$clr.ambient", numpy.array([0.2, 0.2, 0.2, 1.0]))
            emissive = mat.properties.get("$clr.emissive", numpy.array([0., 0., 0., 1.0]))
            shininess = min(mat.properties.get("$mat.shininess", 1.0), 128)
            wireframe = mat.properties.get("$mat.wireframe", 0)
            twosided = mat.properties.get("$mat.twosided", 1)
    
            from OpenGL.raw import GL
            setattr(mat, "gl_mat", GL.GLuint(0))
            mat.gl_mat = glGenLists(1)
            glNewList(mat.gl_mat, GL_COMPILE)
    
            glMaterialfv(GL_FRONT_AND_BACK, GL_DIFFUSE, diffuse)
            glMaterialfv(GL_FRONT_AND_BACK, GL_SPECULAR, specular)
            glMaterialfv(GL_FRONT_AND_BACK, GL_AMBIENT, ambient)
            glMaterialfv(GL_FRONT_AND_BACK, GL_EMISSION, emissive)
            glMaterialf(GL_FRONT_AND_BACK, GL_SHININESS, shininess)
            glPolygonMode(GL_FRONT_AND_BACK, GL_LINE if wireframe else GL_FILL)
            glDisable(GL_CULL_FACE) if twosided else glEnable(GL_CULL_FACE)
    
            glEndList()
    
        glCallList(mat.gl_mat)

    
   
    def do_motion(self):

        gl_time = glutGet(GLUT_ELAPSED_TIME)

        # Compute the new position of the camera and set it
        self.x += self.dp * self.lx * 0.01 * (gl_time-self.prev_time)
        self.z += self.dp * self.lz * 0.01 * (gl_time-self.prev_time)
        self.angle += self.drot * 0.1 *  (gl_time-self.prev_time)
        self.lx = math.sin(self.angle)
        self.lz = -math.cos(self.angle)
        self.set_default_camera()

        self.prev_time = gl_time

        # Compute FPS
        self.frames += 1
        if gl_time - self.prev_fps_time >= 1000:
            current_fps = self.frames * 1000 / (gl_time - self.prev_fps_time)
            logger.info('%.0f fps' % current_fps)
            self.frames = 0
            self.prev_fps_time = gl_time

        glutPostRedisplay()

    def recursive_render(self, node):
        """ Main recursive rendering method.
        """

        # save model matrix and apply node transformation
        glPushMatrix()
        m = node.transformation.transpose() # OpenGL row major
        glMultMatrixf(m)

        for mesh in node.meshes:
            self.apply_material(mesh.material)

            glBindBuffer(GL_ARRAY_BUFFER, mesh.gl["vertices"])
            glEnableClientState(GL_VERTEX_ARRAY)
            glVertexPointer(3, GL_FLOAT, 0, None)

            glBindBuffer(GL_ARRAY_BUFFER, mesh.gl["normals"])
            glEnableClientState(GL_NORMAL_ARRAY)
            glNormalPointer(GL_FLOAT, 0, None)

            glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, mesh.gl["triangles"])
            glDrawElements(GL_TRIANGLES,len(mesh.faces) * 3, GL_UNSIGNED_INT, None)

            glDisableClientState(GL_VERTEX_ARRAY)
            glDisableClientState(GL_NORMAL_ARRAY)

            glBindBuffer(GL_ARRAY_BUFFER, 0)
            glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, 0)

        for child in node.children:
            self.recursive_render(child)

        glPopMatrix()


    def display(self):
        """ GLUT callback to redraw OpenGL surface
        """
        glClear(GL_COLOR_BUFFER_BIT|GL_DEPTH_BUFFER_BIT)
    
        self.recursive_render(self.scene.rootnode)
    
        glutSwapBuffers()
        self.do_motion()
        return

    ####################################################################
    ##               GLUT keyboard and mouse callbacks                ##
    ####################################################################
    def onkeypress(self, key, x, y):
        if key == 'c':
            self.fit_scene(restore = True)
            self.set_camera(self.cycle_cameras())
        if key == 'q':
            sys.exit(0)

    def onspecialkeypress(self, key, x, y):

        fraction = 0.05

        if key == GLUT_KEY_UP:
            self.dp = 0.5
        if key == GLUT_KEY_DOWN:
            self.dp = -0.5
        if key == GLUT_KEY_LEFT:
            self.drot = -0.01
        if key == GLUT_KEY_RIGHT:
            self.drot = 0.01

    def onspecialkeyrelease(self, key, x, y):

        if key == GLUT_KEY_UP:
            self.dp = 0.
        if key == GLUT_KEY_DOWN:
            self.dp = 0.
        if key == GLUT_KEY_LEFT:
            self.drot = 0.0
        if key == GLUT_KEY_RIGHT:
            self.drot = 0.0

    def onclick(self, button, state, x, y):
        if button == GLUT_LEFT_BUTTON:
            if state == GLUT_UP:
                self.drot = 0
                self.x_origin = -1
            else: # GLUT_DOWN
                self.x_origin = x

    def onmousemove(self, x, y):
        if self.x_origin >= 0:
            self.drot = (x - self.x_origin) * 0.001

    def render(self, filename=None, fullscreen = False, autofit = True, postprocess = None):
        """

        :param autofit: if true, scale the scene to fit the whole geometry
        in the viewport.
        """
    
        # First initialize the openGL context
        glutInit(sys.argv)
        glutInitDisplayMode(GLUT_DOUBLE | GLUT_RGB | GLUT_DEPTH)
        if not fullscreen:
            glutInitWindowSize(width, height)
            glutCreateWindow(name)
        else:
            glutGameModeString("1024x768")
            if glutGameModeGet(GLUT_GAME_MODE_POSSIBLE):
                glutEnterGameMode()
            else:
                print("Fullscreen mode not available!")
                sys.exit(1)

        self.load_dae(filename, postprocess = postprocess)

        glClearColor(0.1,0.1,0.1,1.)
        #glShadeModel(GL_SMOOTH)

        glEnable(GL_LIGHTING)

        glEnable(GL_CULL_FACE)
        glEnable(GL_DEPTH_TEST)

        #lightZeroPosition = [10.,4.,10.,1.]
        #lightZeroColor = [0.8,1.0,0.8,1.0] #green tinged
        #glLightfv(GL_LIGHT0, GL_POSITION, lightZeroPosition)
        #glLightfv(GL_LIGHT0, GL_DIFFUSE, lightZeroColor)
        #glLightf(GL_LIGHT0, GL_CONSTANT_ATTENUATION, 0.1)
        #glLightf(GL_LIGHT0, GL_LINEAR_ATTENUATION, 0.05)
        glLightModeli(GL_LIGHT_MODEL_TWO_SIDE, GL_TRUE)
        glEnable(GL_NORMALIZE)
        glEnable(GL_LIGHT0)
    
        glutDisplayFunc(self.display)


        glMatrixMode(GL_PROJECTION)
        glLoadIdentity()
        gluPerspective(35.0, width/float(height) , 0.10, 100.0)
        glMatrixMode(GL_MODELVIEW)
        self.set_default_camera()

        if autofit:
            # scale the whole asset to fit into our view frustum·
            self.fit_scene()

        glPushMatrix()

        # Register GLUT callbacks for keyboard and mouse
        glutKeyboardFunc(self.onkeypress)
        glutSpecialFunc(self.onspecialkeypress)
        glutIgnoreKeyRepeat(1)
        glutSpecialUpFunc(self.onspecialkeyrelease)

        glutMouseFunc(self.onclick)
        glutMotionFunc(self.onmousemove)

        glutMainLoop()


if __name__ == '__main__':
    if not len(sys.argv) > 1:
        print("Usage: " + __file__ + " <model>")
        sys.exit(0)

    glrender = GLRenderer()
    glrender.render(sys.argv[1], fullscreen = False, postprocess = aiProcessPreset_TargetRealtime_MaxQuality)


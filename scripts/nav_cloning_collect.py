#!/usr/bin/env python3
from __future__ import print_function
import roslib
roslib.load_manifest('nav_cloning')
import rospy
import cv2
from geometry_msgs.msg import PoseWithCovarianceStamped,Twist
from sensor_msgs.msg import Image
from cv_bridge import CvBridge, CvBridgeError
from nav_cloning_net import *
from skimage.transform import resize
from geometry_msgs.msg import Twist
from geometry_msgs.msg import PoseArray
from std_msgs.msg import Int8
from std_srvs.srv import Trigger
from nav_msgs.msg import Path
from geometry_msgs.msg import PoseWithCovarianceStamped
from std_srvs.srv import Empty
from geometry_msgs.msg import PoseStamped

from gazebo_msgs.srv import SetModelState
from gazebo_msgs.srv import GetModelState
from gazebo_msgs.msg import ModelState

import math
import tf

from std_srvs.srv import SetBool, SetBoolResponse
import csv
import os
import time
import copy
import sys

class cource_following_learning_node:
    def __init__(self):
        rospy.init_node('cource_following_learning_node', anonymous=True)
        self.bridge = CvBridge()
        self.image_sub = rospy.Subscriber("/camera/rgb/image_raw", Image, self.callback)
        self.image_left_sub = rospy.Subscriber("/camera_left/rgb/image_raw", Image, self.callback_left_camera)
        self.image_right_sub = rospy.Subscriber("/camera_right/rgb/image_raw", Image, self.callback_right_camera)
        self.vel_sub = rospy.Subscriber("/nav_vel", Twist, self.callback_vel)
        self.action_pub = rospy.Publisher("action", Int8, queue_size=1)
        self.nav_pub = rospy.Publisher('/cmd_vel', Twist, queue_size=10)
        self.min_distance = 0.0
        self.action = 0.0
        self.vel = Twist()
        self.cv_image = np.zeros((480,640,3), np.uint8)
        self.cv_left_image = np.zeros((480,640,3), np.uint8)
        self.cv_right_image = np.zeros((480,640,3), np.uint8)
        self.init = True
        self.start_time = time.strftime("%Y%m%d_%H:%M:%S")
        self.path = roslib.packages.get_pkg_dir('nav_cloning') + '/data/result/'
        self.collect_data_srv = rospy.Service('/collect_data', Trigger, self.collect_data)
        self.goal_pub_srv = rospy.Service('/goal_pub', Trigger, self.goal_pub)
        self.save_img_no = 0
        self.save_img_no1= 0
        self.save_img_no2 = 0
        self.goal_no = 0
        self.count_no = 0
        self.csv_path = roslib.packages.get_pkg_dir('nav_cloning') + '/data/analysis/'
        self.pos_list = []
        self.goal_list = []
        self.cur_pos = []
        self.pos = PoseWithCovarianceStamped()
        self.g_pos = PoseStamped()
        self.orientation = 0
        self.r = rospy.Rate(10)
        self.capture_rate = rospy.Rate(0.5)
        rospy.wait_for_service('/gazebo/set_model_state')
        self.state = ModelState()
        self.state.model_name = 'mobile_base'
        self.amcl_pose_pub = rospy.Publisher('initialpose', PoseWithCovarianceStamped, queue_size=1)
        self.simple_goal_pub = rospy.Publisher('move_base_simple/goal', PoseStamped, queue_size=10)
        os.makedirs(self.path + self.start_time)
        os.makedirs(self.path + "analysis/img/" + self.start_time)
        os.makedirs(self.path + "analysis/ang/" + self.start_time)
        self.dl = deep_learning(n_action=1)

        with open(self.csv_path + 'traceable_pos_fix.csv', 'r') as fs:
            for row in fs:
                self.pos_list.append(row)
            # self.cur_pos = self.pos_list[self.save_img_no]

    def capture_img(self):
            Flag = True
            try:
                cv2.imwrite(self.path + "analysis/img/" + self.start_time + "/center" + str(self.save_img_no) + "_" + self.ang_no + ".jpg", self.cv_image)
                cv2.imwrite(self.path + "analysis/img/" + self.start_time + "/right" + str(self.save_img_no) + "_" + self.ang_no + ".jpg", self.cv_right_image)
                cv2.imwrite(self.path + "analysis/img/" + self.start_time + "/left" + str(self.save_img_no) + "_" + self.ang_no + ".jpg", self.cv_left_image)
            except:
                print('Not save image')
                Flag = False
            finally:
                if Flag:
                    print('Save image Number:', self.save_img_no)

    def capture_ang(self):
            line = [str(self.save_img_no), str(self.action)]
            with open(self.path + "analysis/ang/" + self.start_time + '/ang.csv', 'a') as f:
                writer = csv.writer(f, lineterminator='\n')
                writer.writerow(line)
    
    def read_csv(self):
            # if self.init:
            #     f = open(self.csv_path + 'traceable_pos.csv', 'r')
            #     for row in f:
            #         self.pos_list.append(row)
            #     self.init = False
            # cur_pos = self.pos_list[self.save_img_no]
            self.cur_pos = self.pos_list[self.save_img_no]
            pos = self.cur_pos.split(',')
            x = float(pos[1])
            y = float(pos[2])
            theta = float(pos[3])
            # print('Moving_pose:', x, y, theta)
            return x, y, theta

    def simple_goal(self):
            # fs = open(self.csv_path + 'traceable_pos_fix.csv', 'r')
            # for row in fs:
            #     self.goal_list2.append(row)

            # goal_pos2 = self.goal_list[self.save_img_no1]
            # simple_pos = goal_pos2.split(',')
            self.cur_pos = self.pos_list[self.save_img_no + 14]
            simple_pos = self.cur_pos.split(',')
            x = float(simple_pos[1])
            y = float(simple_pos[2])

            self.g_pos.header.stamp = rospy.Time.now()

            self.g_pos.header.frame_id = 'map'
            self.g_pos.pose.position.x = x - 11.252
            self.g_pos.pose.position.y = y - 16.70
            self.g_pos.pose.position.z = 0

            self.g_pos.pose.orientation.x = 0 
            self.g_pos.pose.orientation.y = 0
            self.g_pos.pose.orientation.z = 0
            self.g_pos.pose.orientation.w = 0.999

            self.simple_goal_pub.publish(self.g_pos)

    def robot_moving(self, x, y, angle):
            #amcl
            #replace_pose = PoseWithCovarianceStamped()

            self.pos.header.stamp = rospy.Time.now()

            self.pos.header.frame_id = 'map'
            self.pos.pose.pose.position.x = x - 11.252
            self.pos.pose.pose.position.y = y - 16.70

            quaternion_ = tf.transformations.quaternion_from_euler(0, 0, angle)

            self.pos.pose.pose.orientation.x = quaternion_[0]
            self.pos.pose.pose.orientation.y = quaternion_[1]
            self.pos.pose.pose.orientation.z = quaternion_[2]
            self.pos.pose.pose.orientation.w = quaternion_[3]
            self.pos.pose.covariance = [0.25, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.25, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.06853892326654787]
            
            # self.pos.pose.covariance = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.06853892326654787]

            # self.amcl_pose_pub.publish(self.pos)
            #gazebo
            for offset_ang in [-5, 0, 5]:
                the = angle + math.radians(offset_ang)
                the = the - 2.0 * math.pi if the >  math.pi else the
                the = the + 2.0 * math.pi if the < -math.pi else the
                self.state.pose.position.x = x
                self.state.pose.position.y = y
                quaternion = tf.transformations.quaternion_from_euler(0, 0, the)
                self.state.pose.orientation.x = quaternion[0]
                self.state.pose.orientation.y = quaternion[1]
                self.state.pose.orientation.z = quaternion[2]
                self.state.pose.orientation.w = quaternion[3]

                if offset_ang == -5:
                    self.ang_no = "right"

                if offset_ang == 0:
                    self.ang_no = "center"

                if offset_ang == +5:
                    self.ang_no = "left"

                try:
                    set_state = rospy.ServiceProxy('/gazebo/set_model_state', SetModelState)
                    resp = set_state( self.state )
                    
                    # img = resize(self.cv_image, (48, 64), mode='constant')
                    # r, g, b = cv2.split(img)
                    # imgobj = np.asanyarray([r, g, b])

                    # img_left = resize(self.cv_left_image, (48, 64), mode='constant')
                    # r, g, b = cv2.split(img_left)
                    # imgobj_left = np.asanyarray([r, g, b])

                    # img_right = resize(self.cv_right_image, (48, 64), mode='constant')
                    # r, g, b = cv2.split(img_right)
                    # imgobj_right = np.asanyarray([r, g, b])
                    
                    # self.dl.make_dataset(imgobj, self.action)
                    # self.dl.make_dataset(imgobj_left, self.action - 0.2)
                    # self.dl.make_dataset(imgobj_right, self.action + 0.2)

                    # if self.goal_no == 11:
                    #     self.save_img_no1 += 1
                    #     os.system('rosservice call /move_base/clear_costmaps')
                    #     self.simple_goal()
                    #     self.goal_no = -10

                    if offset_ang == 0 and self.save_img_no % 7 == 0:
                        self.simple_goal()
                        os.system('rosservice call /move_base/clear_costmaps')
                    
                    if offset_ang == -5:
                        self.amcl_pose_pub.publish(self.pos)
                        # if self.save_img_no % 7 == 0:
                        #     self.amcl_pose_pub.publish(self.pos)

                    #test
                    self.capture_img()
                    self.capture_ang()
                except rospy.ServiceException as e:
                    print("Service call failed: %s" % e)
                self.r.sleep()
                self.r.sleep()
                self.r.sleep()
            
            self.r.sleep()
            self.r.sleep()
            self.r.sleep()
        

    def goal_pub(self):
        rospy.wait_for_service('/goal_pub')
        service = rospy.ServiceProxy('/goal_pub', Trigger)
        self.simple_goal()
    
    def collect_data(self, data):
        rospy.wait_for_service('/collect_data')
        service = rospy.ServiceProxy('/collect_data', Trigger)
        self.goal_pub()

        for i in range(900):
            x, y, theta = self.read_csv()
            self.robot_moving(x, y, theta)
            self.count_no += 1
            # print("current_position:", x, y, theta)

            self.save_img_no += 1
            # if self.save_img_no == 7:
            #     self.save_img_no = 0
            self.capture_rate.sleep()
            if i == 885:
                # for j in range(4000):
                #     self.dl.trains()
                # self.dl.save("/home/y-takahashi/catkin_ws/src/nav_cloning/data/result/")
                os.system('killall roslaunch')
                sys.exit()

    def callback(self, data):
        try:
            self.cv_image = self.bridge.imgmsg_to_cv2(data, "bgr8")
        except CvBridgeError as e:
            print(e)

    def callback_left_camera(self, data):
        try:
            self.cv_left_image = self.bridge.imgmsg_to_cv2(data, "bgr8")
        except CvBridgeError as e:
            print(e)

    def callback_right_camera(self, data):
        try:
            self.cv_right_image = self.bridge.imgmsg_to_cv2(data, "bgr8")
        except CvBridgeError as e:
            print(e)

    def callback_vel(self, data):
        self.vel = data
        self.action = self.vel.angular.z
        

if __name__ == '__main__':
    rg = cource_following_learning_node()
    DURATION = 0.2
    r = rospy.Rate(1 / DURATION)
    while not rospy.is_shutdown():
        # rg.loop()
        r.sleep() 
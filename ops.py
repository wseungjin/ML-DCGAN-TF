import tensorflow as tf
import numpy as np
from utils import pytorch_xavier_weight_factor, pytorch_kaiming_weight_factor

##################################################################################
# Initialization
##################################################################################

"""
pytorch xavier (gain)
https://pytorch.org/docs/stable/_modules/torch/nn/init.html
USE < tf.contrib.layers.variance_scaling_initializer() >
if uniform :
    factor = gain * gain
    mode = 'FAN_AVG'
else :
    factor = (gain * gain) / 1.3
    mode = 'FAN_AVG'
    
pytorch : trunc_stddev = gain * sqrt(2 / (fan_in + fan_out))
tensorflow  : trunc_stddev = sqrt(1.3 * factor * 2 / (fan_in + fan_out))
"""

"""
pytorch kaiming (a=0)
https://pytorch.org/docs/stable/_modules/torch/nn/init.html
if uniform :
    a = 0 -> gain = sqrt(2)
    factor = gain * gain
    mode='FAN_IN'
else :
    a = 0 -> gain = sqrt(2)
    factor = (gain * gain) / 1.3
    mode = 'FAN_OUT', # FAN_OUT is correct, but more use 'FAN_IN
    
pytorch : trunc_stddev = gain * sqrt(2 / fan_in)
tensorflow  : trunc_stddev = sqrt(1.3 * factor * 2 / fan_in)
"""

# Xavier : tf.contrib.layers.xavier_initializer()
# He : tf.contrib.layers.variance_scaling_initializer()
# Normal : tf.random_normal_initializer(mean=0.0, stddev=0.02)
# Truncated_normal : tf.truncated_normal_initializer(mean=0.0, stddev=0.02)
# Orthogonal : tf.orthogonal_initializer(0.02)

##################################################################################
# Regularization
##################################################################################

# l2_decay : tf.contrib.layers.l2_regularizer(0.0001)
# orthogonal_regularizer : orthogonal_regularizer(0.0001) # orthogonal_regularizer_fully(0.0001)

# factor, mode, uniform = pytorch_xavier_weight_factor(gain=0.02, uniform=False)
# weight_init = tf_contrib.layers.variance_scaling_initializer(factor=factor, mode=mode, uniform=uniform)

weight_init = tf.truncated_normal_initializer(mean=0.0, stddev=0.02)
weight_regularizer = tf.contrib.layers.l2_regularizer(0.0001)
weight_regularizer_fully = tf.contrib.layers.l2_regularizer(0.0001)

##################################################################################
# Layers
##################################################################################

# padding='SAME' ======> pad = floor[ (kernel - stride) / 2 ]
def conv(x, channels, kernel=4, stride=2, pad=0, pad_type='zero', use_bias=True, sn=False, scope='conv_0'):
    with tf.variable_scope(scope):
        if pad > 0:
            h = x.get_shape().as_list()[1]
            if h % stride == 0:
                pad = pad * 2
            else:
                pad = max(kernel - (h % stride), 0)

            pad_top = pad // 2
            pad_bottom = pad - pad_top
            pad_left = pad // 2
            pad_right = pad - pad_left

            if pad_type == 'zero':
                x = tf.pad(x, [[0, 0], [pad_top, pad_bottom], [pad_left, pad_right], [0, 0]])
            if pad_type == 'reflect':
                x = tf.pad(x, [[0, 0], [pad_top, pad_bottom], [pad_left, pad_right], [0, 0]], mode='REFLECT')

        if sn:
            w = tf.get_variable("kernel", shape=[kernel, kernel, x.get_shape()[-1], channels], initializer=weight_init,
                                regularizer=weight_regularizer)
            x = tf.nn.conv2d(input=x, filter=spectral_norm(w),
                             strides=[1, stride, stride, 1], padding='VALID')
            if use_bias:
                bias = tf.get_variable("bias", [channels], initializer=tf.constant_initializer(0.0))
                x = tf.nn.bias_add(x, bias)

        else:
            x = tf.layers.conv2d(inputs=x, filters=channels,
                                 kernel_size=kernel, kernel_initializer=weight_init,
                                 kernel_regularizer=weight_regularizer,
                                 strides=stride, use_bias=use_bias)

        return x


def partial_conv(x, channels, kernel=3, stride=2, use_bias=True, padding='SAME', sn=False, scope='conv_0'):
    with tf.variable_scope(scope):
        if padding.lower() == 'SAME'.lower():
            with tf.variable_scope('mask'):
                _, h, w, _ = x.get_shape().as_list()

                slide_window = kernel * kernel
                mask = tf.ones(shape=[1, h, w, 1])

                update_mask = tf.layers.conv2d(mask, filters=1,
                                               kernel_size=kernel, kernel_initializer=tf.constant_initializer(1.0),
                                               strides=stride, padding=padding, use_bias=False, trainable=False)

                mask_ratio = slide_window / (update_mask + 1e-8)
                update_mask = tf.clip_by_value(update_mask, 0.0, 1.0)
                mask_ratio = mask_ratio * update_mask

            with tf.variable_scope('x'):
                if sn:
                    w = tf.get_variable("kernel", shape=[kernel, kernel, x.get_shape()[-1], channels],
                                        initializer=weight_init, regularizer=weight_regularizer)
                    x = tf.nn.conv2d(input=x, filter=spectral_norm(w), strides=[1, stride, stride, 1], padding=padding)
                else:
                    x = tf.layers.conv2d(x, filters=channels,
                                         kernel_size=kernel, kernel_initializer=weight_init,
                                         kernel_regularizer=weight_regularizer,
                                         strides=stride, padding=padding, use_bias=False)
                x = x * mask_ratio

                if use_bias:
                    bias = tf.get_variable("bias", [channels], initializer=tf.constant_initializer(0.0))

                    x = tf.nn.bias_add(x, bias)
                    x = x * update_mask
        else:
            if sn:
                w = tf.get_variable("kernel", shape=[kernel, kernel, x.get_shape()[-1], channels],
                                    initializer=weight_init, regularizer=weight_regularizer)
                x = tf.nn.conv2d(input=x, filter=spectral_norm(w), strides=[1, stride, stride, 1], padding=padding)
                if use_bias:
                    bias = tf.get_variable("bias", [channels], initializer=tf.constant_initializer(0.0))

                    x = tf.nn.bias_add(x, bias)
            else:
                x = tf.layers.conv2d(x, filters=channels,
                                     kernel_size=kernel, kernel_initializer=weight_init,
                                     kernel_regularizer=weight_regularizer,
                                     strides=stride, padding=padding, use_bias=use_bias)

        return x


def dilate_conv(x, channels, kernel=3, rate=2, use_bias=True, padding='SAME', sn=False, scope='conv_0'):
    with tf.variable_scope(scope):
        w = tf.get_variable("kernel", shape=[kernel, kernel, x.get_shape()[-1], channels], initializer=weight_init,
                            regularizer=weight_regularizer)
        if sn:
            x = tf.nn.atrous_conv2d(x, spectral_norm(w), rate=rate, padding=padding)
        else:
            x = tf.nn.atrous_conv2d(x, w, rate=rate, padding=padding)

        if use_bias:
            bias = tf.get_variable("bias", [channels], initializer=tf.constant_initializer(0.0))
            x = tf.nn.bias_add(x, bias)

        return x


def deconv(x, channels, kernel=4, stride=2, padding='SAME', use_bias=True, sn=False, scope='deconv_0'):
    with tf.variable_scope(scope):
        x_shape = x.get_shape().as_list()

        if padding == 'SAME':
            output_shape = [x_shape[0], x_shape[1] * stride, x_shape[2] * stride, channels]

        else:
            output_shape = [x_shape[0], x_shape[1] * stride + max(kernel - stride, 0),
                            x_shape[2] * stride + max(kernel - stride, 0), channels]

        if sn:
            w = tf.get_variable("kernel", shape=[kernel, kernel, channels, x.get_shape()[-1]], initializer=weight_init,
                                regularizer=weight_regularizer)
            x = tf.nn.conv2d_transpose(x, filter=spectral_norm(w), output_shape=output_shape,
                                       strides=[1, stride, stride, 1], padding=padding)

            if use_bias:
                bias = tf.get_variable("bias", [channels], initializer=tf.constant_initializer(0.0))
                x = tf.nn.bias_add(x, bias)

        else:
            x = tf.layers.conv2d_transpose(inputs=x, filters=channels,
                                           kernel_size=kernel, kernel_initializer=weight_init,
                                           kernel_regularizer=weight_regularizer,
                                           strides=stride, padding=padding, use_bias=use_bias)

        return x


def conv_pixel_shuffle_up(x, scale_factor=2, use_bias=True, sn=False, scope='pixel_shuffle'):
    channel = x.get_shape()[-1] * (scale_factor ** 2)
    x = conv(x, channel, kernel=1, stride=1, use_bias=use_bias, sn=sn, scope=scope)
    x = tf.depth_to_space(x, block_size=scale_factor)

    return x


def conv_pixel_shuffle_down(x, scale_factor=2, use_bias=True, sn=False, scope='pixel_shuffle'):
    channel = x.get_shape()[-1] // (scale_factor ** 2)
    x = conv(x, channel, kernel=1, stride=1, use_bias=use_bias, sn=sn, scope=scope)
    x = tf.space_to_depth(x, block_size=scale_factor)

    return x


def fully_connected(x, units, use_bias=True, sn=False, scope='linear'):
    with tf.variable_scope(scope):
        x = flatten(x)
        shape = x.get_shape().as_list()
        channels = shape[-1]

        if sn:
            w = tf.get_variable("kernel", [channels, units], tf.float32,
                                initializer=weight_init, regularizer=weight_regularizer_fully)
            if use_bias:
                bias = tf.get_variable("bias", [units],
                                       initializer=tf.constant_initializer(0.0))

                x = tf.matmul(x, spectral_norm(w)) + bias
            else:
                x = tf.matmul(x, spectral_norm(w))

        else:
            x = tf.layers.dense(x, units=units, kernel_initializer=weight_init,
                                kernel_regularizer=weight_regularizer_fully,
                                use_bias=use_bias)

        return x


##################################################################################
# Blocks
##################################################################################

def resblock(x_init, channels, use_bias=True, is_training=True, sn=False, scope='resblock'):
    with tf.variable_scope(scope):
        with tf.variable_scope('res1'):
            x = conv(x_init, channels, kernel=3, stride=1, pad=1, use_bias=use_bias, sn=sn)
            x = batch_norm(x, is_training)
            x = relu(x)

        with tf.variable_scope('res2'):
            x = conv(x, channels, kernel=3, stride=1, pad=1, use_bias=use_bias, sn=sn)
            x = batch_norm(x, is_training)

        return x + x_init


def resblock_up(x_init, channels, use_bias=True, is_training=True, sn=False, scope='resblock_up'):
    with tf.variable_scope(scope):
        with tf.variable_scope('res1'):
            x = deconv(x_init, channels, kernel=3, stride=2, use_bias=use_bias, sn=sn)
            x = batch_norm(x, is_training)
            x = relu(x)

        with tf.variable_scope('res2'):
            x = deconv(x, channels, kernel=3, stride=1, use_bias=use_bias, sn=sn)
            x = batch_norm(x, is_training)

        with tf.variable_scope('skip'):
            x_init = deconv(x_init, channels, kernel=3, stride=2, use_bias=use_bias, sn=sn)

    return relu(x + x_init)


def resblock_up_condition(x_init, z, channels, use_bias=True, is_training=True, sn=False, scope='resblock_up'):
    # See https://github.com/taki0112/BigGAN-Tensorflow
    with tf.variable_scope(scope):
        with tf.variable_scope('res1'):
            x = deconv(x_init, channels, kernel=3, stride=2, use_bias=use_bias, sn=sn)
            x = condition_batch_norm(x, z, is_training)
            x = relu(x)

        with tf.variable_scope('res2'):
            x = deconv(x, channels, kernel=3, stride=1, use_bias=use_bias, sn=sn)
            x = condition_batch_norm(x, z, is_training)

        with tf.variable_scope('skip'):
            x_init = deconv(x_init, channels, kernel=3, stride=2, use_bias=use_bias, sn=sn)

    return relu(x + x_init)


def resblock_down(x_init, channels, use_bias=True, is_training=True, sn=False, scope='resblock_down'):
    with tf.variable_scope(scope):
        with tf.variable_scope('res1'):
            x = conv(x_init, channels, kernel=3, stride=2, pad=1, use_bias=use_bias, sn=sn)
            x = batch_norm(x, is_training)
            x = relu(x)

        with tf.variable_scope('res2'):
            x = conv(x, channels, kernel=3, stride=1, pad=1, use_bias=use_bias, sn=sn)
            x = batch_norm(x, is_training)

        with tf.variable_scope('skip'):
            x_init = conv(x_init, channels, kernel=3, stride=2, pad=1, use_bias=use_bias, sn=sn)

    return relu(x + x_init)

def denseblock(x_init, channels, n_db=6, use_bias=True, is_training=True, sn=False, scope='denseblock') :
    with tf.variable_scope(scope) :
        layers = []
        layers.append(x_init)

        with tf.variable_scope('bottle_neck_0') :
            x = conv(x_init, 4 * channels, kernel=1, stride=1, use_bias=use_bias, sn=sn, scope='conv_0')
            x = batch_norm(x, is_training, scope='batch_norm_0')
            x = relu(x)

            x = conv(x, channels, kernel=3, stride=1, pad=1, use_bias=use_bias, sn=sn, scope='conv_1')
            x = batch_norm(x, is_training, scope='batch_norm_1')
            x = relu(x)

            layers.append(x)

        for i in range(1, n_db) :
            with tf.variable_scope('bottle_neck_' + str(i)) :
                x = tf.concat(layers, axis=-1)

                x = conv(x, 4 * channels, kernel=1, stride=1, use_bias=use_bias, sn=sn, scope='conv_0')
                x = batch_norm(x, is_training, scope='batch_norm_0')
                x = relu(x)

                x = conv(x, channels, kernel=3, stride=1, pad=1, use_bias=use_bias, sn=sn, scope='conv_1')
                x = batch_norm(x, is_training, scope='batch_norm_1')
                x = relu(x)

                layers.append(x)

        x = tf.concat(layers, axis=-1)

        return x


def res_denseblock(x_init, channels, n_rdb=20, n_rdb_conv=6, use_bias=True, is_training=True, sn=False, scope='res_denseblock'):
    with tf.variable_scope(scope):
        RDBs = []
        x_input = x_init

        """
        n_rdb = 20 ( RDB number )
        n_rdb_conv = 6 ( per RDB conv layer )
        """

        for k in range(n_rdb):
            with tf.variable_scope('RDB_' + str(k)):
                layers = []
                layers.append(x_init)

                x = conv(x_init, channels, kernel=3, stride=1, pad=1, use_bias=use_bias, sn=sn, scope='conv_0')
                x = batch_norm(x, is_training, scope='batch_norm_0')
                x = relu(x)

                layers.append(x)

                for i in range(1, n_rdb_conv):
                    x = tf.concat(layers, axis=-1)

                    x = conv(x, channels, kernel=3, stride=1, pad=1, use_bias=use_bias, sn=sn, scope='conv_' + str(i))
                    x = batch_norm(x, is_training, scope='batch_norm_' + str(i))
                    x = relu(x)

                    layers.append(x)

                # Local feature fusion
                x = tf.concat(layers, axis=-1)
                x = conv(x, channels, kernel=1, stride=1, use_bias=use_bias, sn=sn, scope='conv_last')

                # Local residual learning
                x = x_init + x

                RDBs.append(x)
                x_init = x

        with tf.variable_scope('GFF_1x1'):
            x = tf.concat(RDBs, axis=-1)
            x = conv(x, channels, kernel=1, stride=1, use_bias=use_bias, sn=sn, scope='conv')

        with tf.variable_scope('GFF_3x3'):
            x = conv(x, channels, kernel=3, stride=1, pad=1, use_bias=use_bias, sn=sn, scope='conv')


        # Global residual learning
        x = x_input + x

        return x

def self_attention(x, channels, use_bias=True, sn=False, scope='self_attention'):
    with tf.variable_scope(scope):
        f = conv(x, channels // 8, kernel=1, stride=1, use_bias=use_bias, sn=sn, scope='f_conv')  # [bs, h, w, c']
        g = conv(x, channels // 8, kernel=1, stride=1, use_bias=use_bias, sn=sn, scope='g_conv')  # [bs, h, w, c']
        h = conv(x, channels, kernel=1, stride=1, use_bias=use_bias, sn=sn, scope='h_conv')  # [bs, h, w, c]

        # N = h * w
        s = tf.matmul(hw_flatten(g), hw_flatten(f), transpose_b=True)  # # [bs, N, N]

        beta = tf.nn.softmax(s)  # attention map

        o = tf.matmul(beta, hw_flatten(h))  # [bs, N, C]
        gamma = tf.get_variable("gamma", [1], initializer=tf.constant_initializer(0.0))

        o = tf.reshape(o, shape=x.shape)  # [bs, h, w, C]
        x = gamma * o + x

    return x


def self_attention_with_pooling(x, channels, use_bias=True, sn=False, scope='self_attention'):
    with tf.variable_scope(scope):
        f = conv(x, channels // 8, kernel=1, stride=1, use_bias=use_bias, sn=sn, scope='f_conv')  # [bs, h, w, c']
        f = max_pooling(f)

        g = conv(x, channels // 8, kernel=1, stride=1, use_bias=use_bias, sn=sn, scope='g_conv')  # [bs, h, w, c']

        h = conv(x, channels // 2, kernel=1, stride=1, use_bias=use_bias, sn=sn, scope='h_conv')  # [bs, h, w, c]
        h = max_pooling(h)

        # N = h * w
        s = tf.matmul(hw_flatten(g), hw_flatten(f), transpose_b=True)  # # [bs, N, N]

        beta = tf.nn.softmax(s)  # attention map

        o = tf.matmul(beta, hw_flatten(h))  # [bs, N, C]
        gamma = tf.get_variable("gamma", [1], initializer=tf.constant_initializer(0.0))

        o = tf.reshape(o, shape=[x.shape[0], x.shape[1], x.shape[2], channels // 2])  # [bs, h, w, C]
        o = conv(o, channels, kernel=1, stride=1, use_bias=use_bias, sn=sn, scope='attn_conv')
        x = gamma * o + x

    return x


def squeeze_excitation(x, channels, ratio=16, use_bias=True, sn=False, scope='senet'):
    with tf.variable_scope(scope):
        squeeze = global_avg_pooling(x)

        excitation = fully_connected(squeeze, units=channels // ratio, use_bias=use_bias, sn=sn, scope='fc1')
        excitation = relu(excitation)
        excitation = fully_connected(excitation, units=channels, use_bias=use_bias, sn=sn, scope='fc2')
        excitation = sigmoid(excitation)

        excitation = tf.reshape(excitation, [-1, 1, 1, channels])

        scale = x * excitation

        return scale


def convolution_block_attention(x, channels, ratio=16, use_bias=True, sn=False, scope='cbam'):
    with tf.variable_scope(scope):
        with tf.variable_scope('channel_attention'):
            x_gap = global_avg_pooling(x)
            x_gap = fully_connected(x_gap, units=channels // ratio, use_bias=use_bias, sn=sn, scope='fc1')
            x_gap = relu(x_gap)
            x_gap = fully_connected(x_gap, units=channels, use_bias=use_bias, sn=sn, scope='fc2')

        with tf.variable_scope('channel_attention', reuse=True):
            x_gmp = global_max_pooling(x)
            x_gmp = fully_connected(x_gmp, units=channels // ratio, use_bias=use_bias, sn=sn, scope='fc1')
            x_gmp = relu(x_gmp)
            x_gmp = fully_connected(x_gmp, units=channels, use_bias=use_bias, sn=sn, scope='fc2')

            scale = tf.reshape(x_gap + x_gmp, [-1, 1, 1, channels])
            scale = sigmoid(scale)

            x = x * scale

        with tf.variable_scope('spatial_attention'):
            x_channel_avg_pooling = tf.reduce_mean(x, axis=-1, keepdims=True)
            x_channel_max_pooling = tf.reduce_max(x, axis=-1, keepdims=True)
            scale = tf.concat([x_channel_avg_pooling, x_channel_max_pooling], axis=-1)

            scale = conv(scale, channels=1, kernel=7, stride=1, pad=3, pad_type='reflect', use_bias=False, sn=sn,
                         scope='conv')
            scale = sigmoid(scale)

            x = x * scale

            return x


def global_context_block(x, channels, use_bias=True, sn=False, scope='gc_block'):
    with tf.variable_scope(scope):
        with tf.variable_scope('context_modeling'):
            bs, h, w, c = x.get_shape().as_list()
            input_x = x
            input_x = hw_flatten(input_x)  # [N, H*W, C]
            input_x = tf.transpose(input_x, perm=[0, 2, 1])
            input_x = tf.expand_dims(input_x, axis=1)

            context_mask = conv(x, channels=1, kernel=1, stride=1, use_bias=use_bias, sn=sn, scope='conv')
            context_mask = hw_flatten(context_mask)
            context_mask = tf.nn.softmax(context_mask, axis=1)  # [N, H*W, 1]
            context_mask = tf.transpose(context_mask, perm=[0, 2, 1])
            context_mask = tf.expand_dims(context_mask, axis=-1)

            context = tf.matmul(input_x, context_mask)
            context = tf.reshape(context, shape=[bs, 1, 1, c])

        with tf.variable_scope('transform_0'):
            context_transform = conv(context, channels, kernel=1, stride=1, use_bias=use_bias, sn=sn, scope='conv_0')
            context_transform = layer_norm(context_transform)
            context_transform = relu(context_transform)
            context_transform = conv(context_transform, channels=c, kernel=1, stride=1, use_bias=use_bias, sn=sn, scope='conv_1')
            context_transform = sigmoid(context_transform)

            x = x * context_transform

        with tf.variable_scope('transform_1'):
            context_transform = conv(context, channels, kernel=1, stride=1, use_bias=use_bias, sn=sn, scope='conv_0')
            context_transform = layer_norm(context_transform)
            context_transform = relu(context_transform)
            context_transform = conv(context_transform, channels=c, kernel=1, stride=1, use_bias=use_bias, sn=sn, scope='conv_1')

            x = x + context_transform

        return x

def srm_block(x, channels, use_bias=False, is_training=True, scope='srm_block'):
    with tf.variable_scope(scope) :
        bs, h, w, c = x.get_shape().as_list() # c = channels

        x = tf.reshape(x, shape=[bs, -1, c]) # [bs, h*w, c]

        x_mean, x_var = tf.nn.moments(x, axes=1, keep_dims=True) # [bs, 1, c]
        x_std = tf.sqrt(x_var + 1e-5)

        t = tf.concat([x_mean, x_std], axis=1) # [bs, 2, c]

        z = tf.layers.conv1d(t, channels, kernel_size=2, strides=1, use_bias=use_bias)
        z = batch_norm(z, is_training=is_training)

        g = tf.sigmoid(z)

        x = tf.reshape(x * g, shape=[bs, h, w, c])

        return x


##################################################################################
# Normalization
##################################################################################

def batch_norm(x, is_training=False, scope='batch_norm'):
    """
    if x_norm = tf.layers.batch_normalization
    # ...
    with tf.control_dependencies(tf.get_collection(tf.GraphKeys.UPDATE_OPS)):
        train_op = optimizer.minimize(loss)
    """

    return tf.contrib.layers.batch_norm(x,
                                        decay=0.9, epsilon=1e-05,
                                        center=True, scale=True, updates_collections=None,
                                        is_training=is_training, scope=scope)

    # return tf.layers.batch_normalization(x, momentum=0.9, epsilon=1e-05, center=True, scale=True, training=is_training, name=scope)


def instance_norm(x, scope='instance_norm'):
    return tf.contrib.layers.instance_norm(x,
                                           epsilon=1e-05,
                                           center=True, scale=True,
                                           scope=scope)


def layer_norm(x, scope='layer_norm'):
    return tf.contrib.layers.layer_norm(x,
                                        center=True, scale=True,
                                        scope=scope)


def group_norm(x, groups=32, scope='group_norm'):
    return tf.contrib.layers.group_norm(x, groups=groups, epsilon=1e-05,
                                        center=True, scale=True,
                                        scope=scope)


def adaptive_instance_norm(content, gamma, beta, epsilon=1e-5):
    # gamma, beta = style_mean, style_std from MLP
    # See https://github.com/taki0112/MUNIT-Tensorflow

    c_mean, c_var = tf.nn.moments(content, axes=[1, 2], keep_dims=True)
    c_std = tf.sqrt(c_var + epsilon)

    return gamma * ((content - c_mean) / c_std) + beta


def pixel_norm(x, epsilon=1e-8):
    return x * tf.rsqrt(tf.reduce_mean(tf.square(x), axis=-1, keepdims=True) + epsilon)


def spectral_norm(w, iteration=1):
    w_shape = w.shape.as_list()
    w = tf.reshape(w, [-1, w_shape[-1]])

    u = tf.get_variable("u", [1, w_shape[-1]], initializer=tf.random_normal_initializer(), trainable=False)

    u_hat = u
    v_hat = None
    for i in range(iteration):
        """
        power iteration
        Usually iteration = 1 will be enough
        """
        v_ = tf.matmul(u_hat, tf.transpose(w))
        v_hat = tf.nn.l2_normalize(v_)

        u_ = tf.matmul(v_hat, w)
        u_hat = tf.nn.l2_normalize(u_)

    u_hat = tf.stop_gradient(u_hat)
    v_hat = tf.stop_gradient(v_hat)

    sigma = tf.matmul(tf.matmul(v_hat, w), tf.transpose(u_hat))

    with tf.control_dependencies([u.assign(u_hat)]):
        w_norm = w / sigma
        w_norm = tf.reshape(w_norm, w_shape)

    return w_norm


def condition_batch_norm(x, z, is_training=True, scope='batch_norm'):
    # See https://github.com/taki0112/BigGAN-Tensorflow
    with tf.variable_scope(scope):
        _, _, _, c = x.get_shape().as_list()
        decay = 0.9
        epsilon = 1e-05

        test_mean = tf.get_variable("pop_mean", shape=[c], dtype=tf.float32,
                                    initializer=tf.constant_initializer(0.0), trainable=False)
        test_var = tf.get_variable("pop_var", shape=[c], dtype=tf.float32, initializer=tf.constant_initializer(1.0),
                                   trainable=False)

        beta = fully_connected(z, units=c, scope='beta')
        gamma = fully_connected(z, units=c, scope='gamma')

        beta = tf.reshape(beta, shape=[-1, 1, 1, c])
        gamma = tf.reshape(gamma, shape=[-1, 1, 1, c])

        if is_training:
            batch_mean, batch_var = tf.nn.moments(x, [0, 1, 2])
            ema_mean = tf.assign(test_mean, test_mean * decay + batch_mean * (1 - decay))
            ema_var = tf.assign(test_var, test_var * decay + batch_var * (1 - decay))

            with tf.control_dependencies([ema_mean, ema_var]):
                return tf.nn.batch_normalization(x, batch_mean, batch_var, beta, gamma, epsilon)
        else:
            return tf.nn.batch_normalization(x, test_mean, test_var, beta, gamma, epsilon)


def batch_instance_norm(x, scope='batch_instance_norm'):
    with tf.variable_scope(scope):
        ch = x.shape[-1]
        eps = 1e-5

        batch_mean, batch_sigma = tf.nn.moments(x, axes=[0, 1, 2], keep_dims=True)
        x_batch = (x - batch_mean) / (tf.sqrt(batch_sigma + eps))

        ins_mean, ins_sigma = tf.nn.moments(x, axes=[1, 2], keep_dims=True)
        x_ins = (x - ins_mean) / (tf.sqrt(ins_sigma + eps))

        rho = tf.get_variable("rho", [ch], initializer=tf.constant_initializer(1.0),
                              constraint=lambda x: tf.clip_by_value(x, clip_value_min=0.0, clip_value_max=1.0))
        gamma = tf.get_variable("gamma", [ch], initializer=tf.constant_initializer(1.0))
        beta = tf.get_variable("beta", [ch], initializer=tf.constant_initializer(0.0))

        x_hat = rho * x_batch + (1 - rho) * x_ins
        x_hat = x_hat * gamma + beta

        return x_hat

def switch_norm(x, scope='switch_norm') :
    with tf.variable_scope(scope) :
        ch = x.shape[-1]
        eps = 1e-5

        batch_mean, batch_var = tf.nn.moments(x, [0, 1, 2], keep_dims=True)
        ins_mean, ins_var = tf.nn.moments(x, [1, 2], keep_dims=True)
        layer_mean, layer_var = tf.nn.moments(x, [1, 2, 3], keep_dims=True)

        gamma = tf.get_variable("gamma", [ch], initializer=tf.constant_initializer(1.0))
        beta = tf.get_variable("beta", [ch], initializer=tf.constant_initializer(0.0))

        mean_weight = tf.nn.softmax(tf.get_variable("mean_weight", [3], initializer=tf.constant_initializer(1.0)))
        var_wegiht = tf.nn.softmax(tf.get_variable("var_weight", [3], initializer=tf.constant_initializer(1.0)))

        mean = mean_weight[0] * batch_mean + mean_weight[1] * ins_mean + mean_weight[2] * layer_mean
        var = var_wegiht[0] * batch_var + var_wegiht[1] * ins_var + var_wegiht[2] * layer_var

        x = (x - mean) / (tf.sqrt(var + eps))
        x = x * gamma + beta

        return x

##################################################################################
# Activation Function
##################################################################################

def lrelu(x, alpha=0.01):
    # pytorch alpha is 0.01
    return tf.nn.leaky_relu(x, alpha)


def relu(x):
    return tf.nn.relu(x)


def tanh(x):
    return tf.tanh(x)


def sigmoid(x):
    return tf.sigmoid(x)


def swish(x):
    return x * tf.sigmoid(x)


def elu(x):
    return tf.nn.elu(x)

##################################################################################
# Pooling & Resize
##################################################################################

def up_sample(x, scale_factor=2):
    _, h, w, _ = x.get_shape().as_list()
    new_size = [h * scale_factor, w * scale_factor]
    return tf.image.resize_nearest_neighbor(x, size=new_size)


def global_avg_pooling(x):
    gap = tf.reduce_mean(x, axis=[1, 2], keepdims=True)
    return gap


def global_max_pooling(x):
    gmp = tf.reduce_max(x, axis=[1, 2], keepdims=True)
    return gmp


def max_pooling(x, pool_size=2):
    x = tf.layers.max_pooling2d(x, pool_size=pool_size, strides=pool_size, padding='SAME')
    return x


def avg_pooling(x, pool_size=2):
    x = tf.layers.average_pooling2d(x, pool_size=pool_size, strides=pool_size, padding='SAME')
    return x


def flatten(x):
    return tf.layers.flatten(x)


def hw_flatten(x):
    return tf.reshape(x, shape=[x.shape[0], -1, x.shape[-1]])


##################################################################################
# Loss Function
##################################################################################

def classification_loss(logit, label) :
    loss = tf.reduce_mean(tf.nn.softmax_cross_entropy_with_logits_v2(labels=label, logits=logit))
    prediction = tf.equal(tf.argmax(logit, -1), tf.argmax(label, -1))
    accuracy = tf.reduce_mean(tf.cast(prediction, tf.float32))

    return loss, accuracy

def L1_loss(x, y):
    loss = tf.reduce_mean(tf.abs(x - y))

    return loss


def L2_loss(x, y):
    loss = tf.reduce_mean(tf.square(x - y))

    return loss


def huber_loss(x, y):
    return tf.losses.huber_loss(x, y)

def regularization_loss(scope_name) :
    """
    If you want to use "Regularization"
    g_loss += regularization_loss('generator')
    d_loss += regularization_loss('discriminator')
    """
    collection_regularization = tf.get_collection(tf.GraphKeys.REGULARIZATION_LOSSES)

    loss = []
    for item in collection_regularization :
        if scope_name in item.name :
            loss.append(item)

    return tf.reduce_sum(loss)

def histogram_loss(x, y):
    histogram_x = get_histogram(x)
    histogram_y = get_histogram(y)

    hist_loss = L1_loss(histogram_x, histogram_y)

    return hist_loss

def get_histogram(img, bin_size=0.2):
    hist_entries = []

    img_r, img_g, img_b = tf.split(img, num_or_size_splits=3, axis=-1)

    for img_chan in [img_r, img_g, img_b]:
        for i in np.arange(-1, 1, bin_size):
            gt = tf.greater(img_chan, i)
            leq = tf.less_equal(img_chan, i + bin_size)

            condition = tf.cast(tf.logical_and(gt, leq), tf.float32)
            hist_entries.append(tf.reduce_sum(condition))

    hist = normalization(hist_entries)

    return hist


def normalization(x):
    x = (x - tf.reduce_min(x)) / (tf.reduce_max(x) - tf.reduce_min(x))
    return x

def gram_matrix(x) :
    b, h, w, c = x.get_shape().as_list()

    x = tf.reshape(x, shape=[b, -1, c])

    x = tf.matmul(tf.transpose(x, perm=[0, 2, 1]), x)
    x = x / (h * w * c)

    return x

def gram_style_loss(x, y) :
    _, height, width, channels = x.get_shape().as_list()

    x = gram_matrix(x)
    y = gram_matrix(y)

    loss = L2_loss(x, y) # simple version

    # Original eqn as a constant to divide i.e 1/(4. * (channels ** 2) * (width * height) ** 2)
    # loss = tf.reduce_mean(tf.square(x - y)) / (channels ** 2 * width * height)  # (4.0 * (channels ** 2) * (width * height) ** 2)

    return loss

def color_consistency_loss(x, y) :
    x_mu, x_var = tf.nn.moments(x, axes=[1, 2], keep_dims=True)
    y_mu, y_var = tf.nn.moments(y, axes=[1, 2], keep_dims=True)

    loss = L2_loss(x_mu, y_mu) + 5.0 * L2_loss(x_var, y_var)

    return loss

def dice_loss(n_classes, logits, labels):
    """
    :param n_classes: number of classes
    :param logits: [batch_size, m, n, n_classes] float32, output logits
    :param labels: [batch_size, m, n, 1] int32, class label
    :return:
    """

    # https://github.com/keras-team/keras/issues/9395

    smooth = 1e-7
    dtype = tf.float32

    # alpha=beta=0.5 : dice coefficient
    # alpha=beta=1   : tanimoto coefficient (also known as jaccard)
    # alpha+beta=1   : produces set of F*-scores
    alpha, beta = 0.5, 0.5

    # make onehot label [batch_size, m, n, n_classes]
    # tf.one_hot() will ignore (creates zero vector) labels larger than n_class and less then 0
    onehot_labels = tf.one_hot(tf.squeeze(labels, axis=-1), depth=n_classes, dtype=dtype)

    ones = tf.ones_like(onehot_labels, dtype=dtype)
    predicted = tf.nn.softmax(logits)
    p0 = predicted
    p1 = ones - predicted
    g0 = onehot_labels
    g1 = ones - onehot_labels

    num = tf.reduce_sum(p0 * g0, axis=[0, 1, 2])
    den = num + alpha * tf.reduce_sum(p0 * g1, axis=[0, 1, 2]) + beta * tf.reduce_sum(p1 * g0, axis=[0, 1, 2])

    loss = tf.cast(n_classes, dtype=dtype) - tf.reduce_sum((num + smooth) / (den + smooth))
    return loss


##################################################################################
# GAN Loss Function
##################################################################################

def discriminator_loss(Ra, loss_func, real, fake):
    # Ra = Relativistic
    real_loss = 0
    fake_loss = 0

    if Ra and loss_func.__contains__('wgan'):
        print("No exist [Ra + WGAN], so use the {} loss function".format(loss_func))
        Ra = False

    if Ra:
        real_logit = (real - tf.reduce_mean(fake))
        fake_logit = (fake - tf.reduce_mean(real))

        if loss_func == 'lsgan':
            real_loss = tf.reduce_mean(tf.square(real_logit - 1.0))
            fake_loss = tf.reduce_mean(tf.square(fake_logit + 1.0))

        if loss_func == 'gan' or loss_func == 'gan-gp' or loss_func == 'dragan':
            real_loss = tf.reduce_mean(
                tf.nn.sigmoid_cross_entropy_with_logits(labels=tf.ones_like(real), logits=real_logit))
            fake_loss = tf.reduce_mean(
                tf.nn.sigmoid_cross_entropy_with_logits(labels=tf.zeros_like(fake), logits=fake_logit))

        if loss_func == 'hinge':
            real_loss = tf.reduce_mean(relu(1.0 - real_logit))
            fake_loss = tf.reduce_mean(relu(1.0 + fake_logit))

    else:
        if loss_func.__contains__('wgan'):
            real_loss = -tf.reduce_mean(real)
            fake_loss = tf.reduce_mean(fake)

        if loss_func == 'lsgan':
            real_loss = tf.reduce_mean(tf.square(real - 1.0))
            fake_loss = tf.reduce_mean(tf.square(fake))

        if loss_func == 'gan' or loss_func == 'gan-gp' or loss_func == 'dragan':
            real_loss = tf.reduce_mean(tf.nn.sigmoid_cross_entropy_with_logits(labels=tf.ones_like(real), logits=real))
            fake_loss = tf.reduce_mean(tf.nn.sigmoid_cross_entropy_with_logits(labels=tf.zeros_like(fake), logits=fake))

        if loss_func == 'hinge':
            real_loss = tf.reduce_mean(relu(1.0 - real))
            fake_loss = tf.reduce_mean(relu(1.0 + fake))

    loss = real_loss + fake_loss

    return loss


def generator_loss(Ra, loss_func, real, fake):
    # Ra = Relativistic
    fake_loss = 0
    real_loss = 0

    if Ra and loss_func.__contains__('wgan'):
        print("No exist [Ra + WGAN], so use the {} loss function".format(loss_func))
        Ra = False

    if Ra:
        fake_logit = (fake - tf.reduce_mean(real))
        real_logit = (real - tf.reduce_mean(fake))

        if loss_func == 'lsgan':
            fake_loss = tf.reduce_mean(tf.square(fake_logit - 1.0))
            real_loss = tf.reduce_mean(tf.square(real_logit + 1.0))

        if loss_func == 'gan' or loss_func == 'gan-gp' or loss_func == 'dragan':
            fake_loss = tf.reduce_mean(
                tf.nn.sigmoid_cross_entropy_with_logits(labels=tf.ones_like(fake), logits=fake_logit))
            real_loss = tf.reduce_mean(
                tf.nn.sigmoid_cross_entropy_with_logits(labels=tf.zeros_like(real), logits=real_logit))

        if loss_func == 'hinge':
            fake_loss = tf.reduce_mean(relu(1.0 - fake_logit))
            real_loss = tf.reduce_mean(relu(1.0 + real_logit))

    else:
        if loss_func.__contains__('wgan'):
            fake_loss = -tf.reduce_mean(fake)

        if loss_func == 'lsgan':
            fake_loss = tf.reduce_mean(tf.square(fake - 1.0))

        if loss_func == 'gan' or loss_func == 'gan-gp' or loss_func == 'dragan':
            fake_loss = tf.reduce_mean(tf.nn.sigmoid_cross_entropy_with_logits(labels=tf.ones_like(fake), logits=fake))

        if loss_func == 'hinge':
            fake_loss = -tf.reduce_mean(fake)

    loss = fake_loss + real_loss

    return loss

def vdb_loss(mu, logvar, i_c=0.1) :
    # variational discriminator bottleneck loss
    kl_divergence = 0.5 * tf.reduce_sum(tf.square(mu) + tf.exp(logvar) - 1 - logvar, axis=-1)

    loss = tf.reduce_mean(kl_divergence - i_c)

    return loss

def simple_gp(real_logit, fake_logit, real_images, fake_images, r1_gamma=10, r2_gamma=0) :
    # Used in StyleGAN

    r1_penalty = 0
    r2_penalty = 0

    if r1_gamma != 0 :
        real_loss = tf.reduce_sum(real_logit) # In some cases, you may use reduce_mean
        real_grads = tf.gradients(real_loss, real_images)[0]

        r1_penalty = 0.5 * r1_gamma * tf.reduce_mean(tf.reduce_sum(tf.square(real_grads), axis=[1, 2, 3]))

    if r2_gamma != 0 :
        fake_loss = tf.reduce_sum(fake_logit) # In some cases, you may use reduce_mean
        fake_grads = tf.gradients(fake_loss, fake_images)[0]

        r2_penalty = 0.5 * r2_gamma * tf.reduce_mean(tf.reduce_sum(tf.square(fake_grads), axis=[1, 2, 3]))

    return r1_penalty + r2_penalty


##################################################################################
# KL-Divergence Loss Function
##################################################################################

# typical version
def z_sample(mean, logvar):
    eps = tf.random_normal(tf.shape(mean), mean=0.0, stddev=1.0, dtype=tf.float32)

    return mean + tf.exp(logvar * 0.5) * eps


def kl_loss(mean, logvar):
    # shape : [batch_size, channel]
    loss = 0.5 * tf.reduce_sum(tf.square(mean) + tf.exp(logvar) - 1 - logvar, axis=-1)
    loss = tf.reduce_mean(loss)

    return loss


# version 2
def z_sample_2(mean, var):
    eps = tf.random_normal(tf.shape(mean), mean=0.0, stddev=1.0, dtype=tf.float32)

    return mean + var * eps


def kl_loss_2(mean, var):
    # shape : [batch_size, channel]
    loss = 0.5 * tf.reduce_sum(tf.square(mean) + tf.square(var) - tf.log(1e-8 + tf.square(var)) - 1, axis=-1)
    loss = tf.reduce_mean(loss)

    return loss
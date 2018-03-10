import numpy as np
np.random.seed(42)

from sklearn.model_selection import train_test_split
from sklearn.metrics import roc_auc_score

import tensorflow as tf

from keras.models import Model
from keras.activations import relu
from keras.layers import Input, Dense, Embedding, concatenate, add, merge
from keras.layers import GRU, Bidirectional, LSTM
from keras.layers import Activation, Conv1D, Flatten, Lambda
from keras.layers import GlobalAveragePooling1D, GlobalMaxPooling1D, MaxPooling1D
from keras.layers import SpatialDropout1D
from keras.callbacks import Callback
from keras.layers.normalization import BatchNormalization

import warnings
warnings.filterwarnings('ignore')

import os
os.environ['OMP_NUM_THREADS'] = '4'

from keras import backend as K
from keras.engine.topology import Layer, InputSpec
#from keras import initializations
from keras import initializers, regularizers, constraints
import tensorflow as tf

class KMaxPooling(Layer):
    """
    K-max pooling layer that extracts the k-highest activations from a sequence (2nd dimension).
    TensorFlow backend.
    """
    def __init__(self, k=1, **kwargs):
        super().__init__(**kwargs)
        self.input_spec = InputSpec(ndim=3)
        self.k = k

    def compute_output_shape(self, input_shape):
        return (input_shape[0], (input_shape[2] * self.k))

    def call(self, inputs):
        
        # swap last two dimensions since top_k will be applied along the last dimension
        shifted_input = tf.transpose(inputs, [0, 2, 1])
        
        # extract top_k, returns two tensors [values, indices]
        top_k = tf.nn.top_k(shifted_input, k=self.k, sorted=True, name=None)[0]
        
        # return flattened output
        return Flatten()(top_k)

def auc_roc(y_true, y_pred):
    # any tensorflow metric
    value, update_op = tf.contrib.metrics.streaming_auc(y_pred, y_true)

    # find all variables created for this metric
    metric_vars = [i for i in tf.local_variables() if 'auc_roc' in i.name.split('/')[1]]

    # Add metric variables to GLOBAL_VARIABLES collection.
    # They will be initialized for new session.
    for v in metric_vars:
        tf.add_to_collection(tf.GraphKeys.GLOBAL_VARIABLES, v)

    # force to update metric values
    with tf.control_dependencies([update_op]):
        value = tf.identity(value)
        return value

'''
CNN
'''
def get_CNN_model(**kwargs):
    maxlen = kwargs["maxlen"]
    max_features = kwargs["max_features"]
    embed_size = kwargs["embed_size"]
    embedding_matrix = kwargs["embedding_matrix"]
    dropout = kwargs["dropout"]
    num_filter = kwargs["num_filter"]
    kernel_size = kwargs["kernel_size"]
    reg = kwargs["reg"]
    
    inp = Input(shape=(maxlen, ))
    x = Embedding(max_features, embed_size, weights=[embedding_matrix])(inp)
    x = SpatialDropout1D(dropout)(x)
    x = Conv1D(num_filter, kernel_size, activation='relu',
                kernel_regularizer=regularizers.l2(reg))(x)
    x = GlobalMaxPooling1D()(x)
    outp = Dense(6, activation="sigmoid")(x)
    
    model = Model(inputs=inp, outputs=outp)
    model.compile(loss='binary_crossentropy',
                  optimizer='adam',
                  metrics=['accuracy', auc_roc])
    return model

def get_multiChannel_CNN_model(**kwargs):
    maxlen = kwargs["maxlen"]
    max_features = kwargs["max_features"]
    embed_size1 = kwargs["embed_size1"]
    embedding_matrix1 = kwargs["embedding_matrix1"]
    dropout1 = kwargs["dropout1"]
    num_filter1 = kwargs["num_filter1"]
    kernel_size1 = kwargs["kernel_size1"]
    reg1 = kwargs["reg1"]
    embed_size2 = kwargs["embed_size2"]
    embedding_matrix2 = kwargs["embedding_matrix2"]
    dropout2 = kwargs["dropout2"]
    num_filter2 = kwargs["num_filter2"]
    kernel_size2 = kwargs["kernel_size2"]
    reg2 = kwargs["reg2"]
    
    inp1 = Input(shape=(maxlen,))
    x1 = Embedding(max_features, embed_size1, weights=[embedding_matrix1])(inp1)
    x1 = SpatialDropout1D(dropout1)(x1)
    x1 = Conv1D(num_filter1, kernel_size1, activation='relu',
                kernel_regularizer=regularizers.l2(reg1))(x1)
    x1 = GlobalMaxPooling1D()(x1)

    inp2 = Input(shape=(maxlen,))
    x2 = Embedding(max_features, embed_size2, weights=[embedding_matrix2])(inp2)
    x2 = SpatialDropout1D(dropout2)(x2)
    x2 = Conv1D(num_filter2, kernel_size2, activation='relu',
                kernel_regularizer=regularizers.l2(reg2))(x2)
    x2 = GlobalMaxPooling1D()(x2)
    x2 = Flatten()(x2)

    merged = concatenate([x1, x2])
    outp = Dense(6, activation='sigmoid')(merged)
    
    model = Model(inputs=[inp1, inp2], outputs=outp)
    model.compile(loss='binary_crossentropy',
                  optimizer='adam',
                  metrics=['accuracy', auc_roc])
    return model

def get_dpcnn_model(**kwargs):
    maxlen = kwargs["maxlen"]
    max_features = kwargs["max_features"]
    embed_size = kwargs["embed_size"]
    embedding_matrix = kwargs["embedding_matrix"]
    dropout = kwargs["dropout"]
    num_filter = kwargs["num_filter"]
    kernel_size = kwargs["kernel_size"]
    reg = kwargs["reg"]
    
    inp = Input(shape=(maxlen, ))
    embedding = Embedding(max_features, embed_size, weights=[embedding_matrix])(inp)
    embedding = SpatialDropout1D(dropout)(embedding)
    embedding = Activation('relu')(embedding)  # pre activation
    block1 = Conv1D(num_filter, kernel_size, padding='same',
                    kernel_regularizer=regularizers.l2(reg))(embedding)
    block1 = Activation('relu')(block1)
    block1 = Conv1D(num_filter, kernel_size, padding='same',
                    kernel_regularizer=regularizers.l2(reg))(block1)
    # reshape layer if needed
    conc1 = None
    if num_filter != embed_size:
        embedding_resize = Conv1D(num_filter, kernel_size=1, padding='same', activation='linear',
                                kernel_regularizer=regularizers.l2(reg))(embedding)
        block1 = Lambda(relu)(block1)
        conc1 = add([embedding_resize, block1])
    else:
        conc1 = add([embedding, block1])
    
    # block 2 & block 3 are dpcnn repeating blocks
    downsample1 = MaxPooling1D(pool_size=3, strides=2)(conc1)
    downsample1 = Activation('relu')(downsample1)  # pre activation
    block2 = Conv1D(num_filter, kernel_size, padding='same',
                    kernel_regularizer=regularizers.l2(reg))(downsample1)
    block2 = SpatialDropout1D(dropout)(block2)
    block2 = Activation('relu')(block2)
    block2 = Conv1D(num_filter, kernel_size, padding='same',
                    kernel_regularizer=regularizers.l2(reg))(block2)
    block2 = SpatialDropout1D(dropout)(block2)
    conc2 = add([downsample1, block2])
    
    downsample2 = MaxPooling1D(pool_size=3, strides=2)(conc2)
    downsample2 = Activation('relu')(downsample2)  # pre activation
    block3 = Conv1D(num_filter, kernel_size, padding='same',
                    kernel_regularizer=regularizers.l2(reg))(downsample2)
    block3 = SpatialDropout1D(dropout)(block3)
    block3 = Activation('relu')(block3)
    block3 = Conv1D(num_filter, kernel_size, padding='same',
                    kernel_regularizer=regularizers.l2(reg))(block3)
    block3 = SpatialDropout1D(dropout)(block3)
    conc3 = add([downsample2, block3])
    
    after_pool = MaxPooling1D(pool_size=3, strides=2)(conc3)
    after_pool = Flatten()(after_pool)
    outp = Dense(6, activation="sigmoid")(after_pool)
    
    model = Model(inputs=inp, outputs=outp)
    model.compile(loss='binary_crossentropy',
                  optimizer='adam',
                  metrics=['accuracy', auc_roc])

    return model

def get_textCNN(**kwargs):
    maxlen = kwargs["maxlen"]
    max_features = kwargs["max_features"]
    embed_size = kwargs["embed_size"]
    embedding_matrix = kwargs["embedding_matrix"]
    dropout = kwargs["dropout"]
    num_filter = kwargs["num_filter"]
    kernel_size = kwargs["kernel_size"]
    reg = kwargs["reg"]
    
    inp = Input(shape=(maxlen, ))
    embedding = Embedding(max_features, embed_size, weights=[embedding_matrix])(inp)
    
    block1 = Conv1D(num_filter, 2, padding='same',
                    kernel_regularizer=regularizers.l2(reg))(embedding)
    block1 = BatchNormalization()(block1)
    block1 = Activation('relu')(block1)
    block1 = SpatialDropout1D(dropout)(block1)
    block1 = GlobalMaxPooling1D()(block1)
    
    block2 = Conv1D(num_filter, 3, padding='same',
                    kernel_regularizer=regularizers.l2(reg))(embedding)
    block2 = BatchNormalization()(block2)
    block2 = Activation('relu')(block2)
    block2 = SpatialDropout1D(dropout)(block2)
    block2 = GlobalMaxPooling1D()(block2)
    
    block3 = Conv1D(num_filter, 4, padding='same',
                    kernel_regularizer=regularizers.l2(reg))(embedding)
    block3 = BatchNormalization()(block3)
    block3 = Activation('relu')(block3)
    block3 = SpatialDropout1D(dropout)(block3)
    block3 = GlobalMaxPooling1D()(block3)
    
    conc = concatenate([block1, block2, block3])
    outp = Dense(6, activation="sigmoid")(conc)
    
    model = Model(inputs=inp, outputs=outp)
    model.compile(loss='binary_crossentropy',
                  optimizer='adam',
                  metrics=['accuracy', auc_roc])
    return model

def get_textRCNN_model(**kwargs):
    maxlen = kwargs["maxlen"]
    max_features = kwargs["max_features"]
    embed_size = kwargs["embed_size"]
    embedding_matrix = kwargs["embedding_matrix"]
    dropout = kwargs["dropout"]
    num_filter = kwargs["num_filter"]
    kernel_size = kwargs["kernel_size"]
    reg = kwargs["reg"]
    k = kwargs["kmax"]
    units = kwargs["units"]
    
    inp = Input(shape=(maxlen, ))
    embedding = Embedding(max_features, embed_size, weights=[embedding_matrix])(inp)
    
    r = SpatialDropout1D(dropout)(embedding)
    r = Bidirectional(LSTM(units, return_sequences=True, kernel_regularizer=regularizers.l2(reg)))(r)
    r = SpatialDropout1D(dropout)(r)
    r = Bidirectional(LSTM(units, return_sequences=True, kernel_regularizer=regularizers.l2(reg)))(r)
    
    conc = concatenate([embedding, r])
    
    c = Conv1D(num_filter, 2, padding='same', activation='relu',
                kernel_regularizer=regularizers.l2(reg))(conc)
    c = GlobalMaxPooling1D()(c)
    
    outp = Dense(6, activation="sigmoid")(c)
    model = Model(inputs=inp, outputs=outp)
    model.compile(loss='binary_crossentropy',
                  optimizer='adam',
                  metrics=['accuracy', auc_roc])
    return model


'''
GRU
see ipython notebooks
'''
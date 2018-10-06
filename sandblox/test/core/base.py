from timeit import timeit
from typing import Type

import tensorflow as tf

import sandblox as sx
import sandblox.core.io
import sandblox.util.tf_util as U
from sandblox.test.core.foo import FooLogic


class Suppressed(object):
	# Wrapped classes don't get tested themselves
	class TestBlockBase(object):
		target = None  # type: Type[sx.TFMold]
		bad_target = None  # type: Type[sx.TFMold]
		block_foo_ob = None  # type: sx.TFMold

		def create_block_ob(self, **props) -> sx.TFMold:
			raise NotImplementedError

		def create_bad_block_ob(self, **props) -> sx.TFMold:
			raise NotImplementedError

		OVERHEAD_RATIO_LIMIT = 15

		def __init__(self, method_name: str = 'runTest'):
			super(Suppressed.TestBlockBase, self).__init__(method_name)
			with tf.variable_scope(self.block_foo_ob.scope.rel, reuse=True):
				self.bound_flattened_logic_args = sandblox.core.io.bind_resolved(FooLogic.call, *FooLogic.args, **FooLogic.kwargs)
				self.logic_outs = list(FooLogic.resolved_args_call(FooLogic.call))

			self.options = tf.RunOptions()
			self.options.output_partition_graphs = True

		def test_block_inputs(self):
			self.assertEqual(self.block_foo_ob.i.__dict__, self.bound_flattened_logic_args)

		def test_block_dynamic_inputs(self):
			self.assertEqual(self.block_foo_ob.di, [sx.resolve(*FooLogic.di)])

		def assertEqual(self, first, second, msg=None):
			first, second = U.core_op_name(first), U.core_op_name(second)
			super(Suppressed.TestBlockBase, self).assertEqual(first, second, msg)

		def test_block_out(self):
			self.assertEqual(U.core_op_name(self.block_foo_ob.o.a), U.core_op_name(self.logic_outs[1]))
			self.assertEqual(U.core_op_name(self.block_foo_ob.o.b), U.core_op_name(self.logic_outs[0]))

		def test_block_out_order(self):
			self.assertEqual(U.core_op_name(self.block_foo_ob.oz), U.core_op_name(self.logic_outs))

		def test_run(self):
			with tf.Session() as sess:
				sess.run(tf.variables_initializer(self.block_foo_ob.get_variables()))
				eval_100 = self.block_foo_ob.run(100)

				metadata = tf.RunMetadata()
				eval_0 = self.block_foo_ob.using(self.options, metadata).run(0)
				self.assertTrue(hasattr(metadata, 'partition_graphs') and len(metadata.partition_graphs) > 0)

				self.assertEqual(eval_100[0], eval_0[0] + 100)
				self.assertNotEqual(eval_100[1], eval_0[1])  # Boy aren't you unlucky if you fail this test XD

		def test_non_Out_return_assertion(self):
			with self.assertRaises(AssertionError) as bad_foo_context:
				with tf.Session(graph=tf.Graph()):
					self.create_bad_block_ob(reuse=None)
			self.assertTrue('must either return' in str(bad_foo_context.exception))

		def test_run_overhead(self):
			with tf.Session() as sess:
				sess.run(tf.variables_initializer(self.block_foo_ob.get_variables()))

				run_backup = self.block_foo_ob.built_fn.sess.run
				self.block_foo_ob.built_fn.sess.run = no_op_fn

				actual_elapse = timeit(lambda: self.block_foo_ob.run(100), number=1000)
				stub_elapse = timeit(lambda: self.block_foo_ob.built_fn.sess.run(), number=1000)

				self.block_foo_ob.built_fn.sess.run = run_backup

				overhead_ratio = (actual_elapse - stub_elapse) / stub_elapse

				if overhead_ratio > Suppressed.TestBlockBase.OVERHEAD_RATIO_LIMIT:
					self.fail('Overhead factor of %.1f exceeded limit of %.1f' % (
						overhead_ratio, Suppressed.TestBlockBase.OVERHEAD_RATIO_LIMIT))
				else:
					print('%s: Overhead factor of %.1f within limit of %.1f' % (
						type(self).__name__, overhead_ratio, Suppressed.TestBlockBase.OVERHEAD_RATIO_LIMIT))

		# TODO Test scope_name
		# TODO Test is_built
		def test_session_specification(self):
			sess = tf.Session(graph=tf.Graph())
			with tf.Session(graph=tf.Graph()):
				block = self.create_block_ob(session=sess)
				with sess.graph.as_default():
					sess.run(tf.initialize_variables(block.get_variables()))
				self.assertEqual(block.sess, sess)
				block.run(100)
				block.set_session(tf.Session())
				self.assertNotEqual(block.sess, sess)
				with self.assertRaises(RuntimeError) as ctx:
					block.run(100)
				self.assertTrue('graph is empty' in str(ctx.exception))
				with self.assertRaises(AssertionError) as ctx:
					self.create_block_ob(session='some_invalid_session')
				self.assertTrue('must be of type tf.Session' in str(ctx.exception))

		def test_variable_assignment(self):
			with tf.Graph().as_default():
				block1 = self.create_block_ob(scope_name='source')
				block2 = self.create_block_ob(scope_name='target')
				vars1 = block1.get_variables()
				vars2 = block2.get_variables()
				init = tf.variables_initializer(vars1 + vars2)
				assignment_op = block2.assign_vars(block1)
				eq_op = tf.equal(vars1, vars2)
				with tf.Session() as sess:
					sess.run(init)
					self.assertTrue(not sess.run(eq_op))
					sess.run(assignment_op)
					self.assertTrue(sess.run(eq_op))

		def test_reuse(self):
			with tf.Graph().as_default():
				block1 = self.create_block_ob(scope_name='reuse_me')
				block2 = self.create_block_ob(scope_name='reuse_me', reuse=True)
				vars1 = block1.get_variables()
				tf.get_collection(tf.GraphKeys.UPDATE_OPS, block1.scope.exact_abs_pattern)
				vars2 = block2.get_variables()
				init = tf.variables_initializer(vars1 + vars2)
				eq_op = tf.equal(vars1, vars2)
				update_vars_1 = [tf.assign(var, 2) for var in vars1]
				with tf.Session() as sess:
					sess.run(init)
					self.assertTrue(sess.run(eq_op))
					sess.run(update_vars_1)
					self.assertTrue(sess.run(eq_op))


def no_op_fn(*_args, **_kwargs):
	return ()

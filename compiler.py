"""
The Compiler uses the Parser and the Kernel to translate a pure Python function
into a native library. This library can be invoked though several language bindings,
in particular as a native Python module.
"""


import subprocess
from kernel import *
from compiler_constants import *
from compiler_generic import Compiler_Generic
from compiler_intel import Compiler_Intel

class Compiler:

  #Utility functions: output file names
  def get_python_file(k):
    return 'vecpy_%s_python.h'%(k.name)

  def get_java_file(k):
    return 'vecpy_%s_java.h'%(k.name)

  def get_cpp_file(k):
    return 'vecpy_%s_cpp.h'%(k.name)

  def get_kernel_file(k):
    return 'vecpy_%s_kernel.h'%(k.name)

  def get_core_file(k):
    return 'vecpy_%s_core.cpp'%(k.name)

  #Generates the core file
  def compile_core(k, options, include_files):
    if Architecture.is_generic(options.arch):
      suffix = 'scalar'
    elif Architecture.is_intel(options.arch):
      suffix = 'vector'
    else:
      raise Exception('Target architecture not implemented (%s)'%(options.arch['name']))
    src = Formatter()
    src.section('VecPy generated core')
    #Includes
    src += '//Includes'
    src += '#include <pthread.h>'
    src += '#include <stdio.h>'
    src += '#include "%s"'%(Compiler.get_kernel_file(k))
    src += ''
    #Utility functions
    src += '//Utility functions'
    src += 'static void* threadStart(void* v) {'
    src.indent()
    src += '%s_%s((KernelArgs*)v);'%(k.name, suffix)
    src += 'return NULL;'
    src.unindent()
    src += '}'
    src += 'static bool isAligned(void* data) {'
    src.indent()
    src += 'return reinterpret_cast<unsigned long>(data) %% %dUL == 0UL;'%(options.arch['size'] * 4)
    src.unindent()
    src += '}'
    src += 'static bool checkArgs(KernelArgs* args) {'
    src.indent()
    for arg in k.get_arguments():
      src += 'if(!isAligned(args->%s)) {'%(arg.name)
      src.indent()
      src += 'printf("Array not aligned (%s)\\n");'%(arg.name)
      src += 'return false;'
      src.unindent()
      src += '}'
    src += 'return true;'
    src.unindent()
    src += '}'
    src += ''
    #Unified core for all programming interfaces
    src += '//Unified core function'
    src += 'static bool run(KernelArgs* args) {'
    src.indent()
    src += 'if(!checkArgs(args)) {'
    src.indent()
    src += 'printf("Arguments are invalid\\n");'
    src += 'return false;'
    src.unindent()
    src += '}'
    src += '//Compile-time constants'
    src += 'const unsigned int vectorSize = %d;'%(options.arch['size'])
    src += 'const unsigned int numThreads = %d;'%(options.threads)
    src += '//Division of labor'
    src += 'const unsigned int vectorsPerThread = args->N / (vectorSize * numThreads);'
    src += 'const unsigned int elementsPerThread = vectorsPerThread * vectorSize;'
    src += '//Execute on multiple threads'
    src += 'unsigned int offset = 0;'
    src += 'if(elementsPerThread > 0) {'
    src.indent()
    src += 'pthread_t* threads = new pthread_t[numThreads];'
    src += 'KernelArgs* threadArgs = new KernelArgs[numThreads];'
    src += 'for(int t = 0; t < numThreads; t++) {'
    src.indent()
    for arg in k.get_arguments():
      src += 'threadArgs[t].%s = &args->%s[offset];'%(arg.name, arg.name)
    src += 'threadArgs[t].N = elementsPerThread;'
    src += 'offset += elementsPerThread;'
    src += 'pthread_create(&threads[t], NULL, threadStart, (void*)&threadArgs[t]);'
    src.unindent()
    src += '}'
    src += 'for(int t = 0; t < numThreads; t++) {'
    src.indent()
    src += ' pthread_join(threads[t], NULL); '
    src.unindent()
    src += '}'
    src += 'delete [] threads;'
    src += 'delete [] threadArgs;'
    src.unindent()
    src += '}'
    src += 'printf("Vector: %dx%dx%d=%d | Scalar: %d\\n", vectorsPerThread, vectorSize, numThreads, offset, args->N - offset);'
    src += '//Handle any remaining elements'
    src += 'if(offset < args->N) {'
    src.indent()
    src += 'KernelArgs lastArgs;'
    for arg in k.get_arguments():
      src += 'lastArgs.%s = &args->%s[offset];'%(arg.name, arg.name)
    src += 'lastArgs.N = args->N - offset;'
    src += '%s_scalar(&lastArgs);'%(k.name)
    src.unindent()
    src += '}'
    src += 'return true;'
    src.unindent()
    src += '}'
    src += ''
    #Additional includes for each programming language
    src += '//Additional includes for each programming language'
    for file in include_files:
      src += '#include "%s"'%(file)
    src += ''
    #Save code to file
    file_name = Compiler.get_core_file(k)
    with open(file_name, 'w') as file:
      file.write(src.get_code())
    #print('Saved to file: %s'%(file_name))

  #Generates the C++ API
  def compile_cpp(k, options):
    src = Formatter()
    src.section('VecPy generated entry point: C++')
    #Build the argument string
    arg_str = ''
    for arg in k.get_arguments():
      arg_str += '%s* %s, '%(options.type, arg.name)
    #Wrapper for the core function
    src += '//Wrapper for the core function'
    src += 'extern "C" bool %s(%sint N) {'%(k.name, arg_str)
    src.indent()
    src += 'KernelArgs args;'
    for arg in k.get_arguments():
      src += 'args.%s = %s;'%(arg.name, arg.name)
    src += 'args.N = N;'
    src += 'return run(&args);'
    src.unindent()
    src += '}'
    src += ''
    #Save code to file
    file_name = Compiler.get_cpp_file(k)
    with open(file_name, 'w') as file:
      file.write(src.get_code())
    #print('Saved to file: %s'%(file_name))

  #Generates the Python API
  def compile_python(k, options):
    type = options.type
    module_name = 'VecPy_' + k.name
    args = k.get_arguments()
    src = Formatter()
    src.section('VecPy generated entry point: Python')
    #Includes
    src += '//Includes'
    src += '#include <Python.h>'
    src += ''
    #Wrapper for the core function
    src += '//Wrapper for the core function'
    src += 'static PyObject* %s_run(PyObject* self, PyObject* pyArgs) {'%(k.name)
    src.indent()
    src += '//Handles to Python objects and buffers'
    obj_str = ', '.join('*obj_%s'%(arg.name) for arg in args)
    buf_str = ', '.join('buf_%s'%(arg.name) for arg in args)
    src += 'PyObject %s;'%(obj_str)
    src += 'Py_buffer %s;'%(buf_str)
    src += '//Get Python objects'
    obj_str = ', '.join('&obj_%s'%(arg.name) for arg in args)
    src += 'if(!PyArg_ParseTuple(pyArgs, "%s", %s)) {'%('O' * len(args), obj_str)
    src.indent()
    src += 'printf("Error retrieving Python objects\\n");'
    src += 'return NULL;'
    src.unindent()
    src += '}'
    src += '//Get Python buffers from Python objects'
    for arg in args:
      src += 'if(PyObject_GetBuffer(obj_%s, &buf_%s, %s) != 0) {'%(arg.name, arg.name, 'PyBUF_WRITABLE' if arg.output else '0')
      src.indent()
      src += 'printf("Error retrieving Python buffer (%s)\\n");'%(arg.name)
      src += 'return NULL;'
      src.unindent()
      src += '}'
    src += '//Number of elements to process'
    src += 'int N = buf_%s.len / sizeof(%s);'%(args[0].name, type)
    src += '//Check length for all buffers'
    for arg in args:
      src += 'if(buf_%s.len / sizeof(%s) != N) {'%(arg.name, type)
      src.indent()
      src += 'printf("Python buffer sizes don\'t match (%s)\\n");'%(arg.name)
      src += 'return NULL;'
      src.unindent()
      src += '}'
    src += '//Extract input arrays from buffers'
    src += 'KernelArgs args;'
    for arg in args:
      src += 'args.%s = (%s*)buf_%s.buf;'%(arg.name, type, arg.name)
    src += 'args.N = N;'
    src += '//Run the kernel'
    src += 'bool result = run(&args);'
    src += '//Release buffers'
    for arg in args:
      src += 'PyBuffer_Release(&buf_%s);'%(arg.name)
    src += '//Return the result'
    src += 'if(result) { Py_RETURN_TRUE; } else { printf("Kernel reported failure\\n"); Py_RETURN_FALSE; }'
    src.unindent()
    src += '}'
    src += ''
    #Module manifest
    src += '//Module manifest'
    src += 'static PyMethodDef module_methods[] = {'
    src.indent()
    src += '{'
    src.indent()
    src += '//Export name, visible within Python'
    src += '"%s",'%(k.name)
    src += '//Pointer to local implementation'
    src += '%s_run,'%(k.name)
    src += '//Accept normal (not keyword) arguments'
    src += 'METH_VARARGS,'
    src += '//Function documentation'
    src += '"%s"'%('\n'.join(k.docstring.splitlines()))
    src.unindent()
    src += '},{NULL, NULL, 0, NULL} //End of manifest entries'
    src.unindent()
    src += '};'
    src += ''
    #Module definition
    src += '//Module definition'
    src += 'static struct PyModuleDef module = {'
    src.indent()
    src += 'PyModuleDef_HEAD_INIT,'
    src += '//Module name'
    src += '"%s",'%(module_name)
    src += '//Module documentation'
    src += '"VecPy module for %s.",'%(k.name)
    src += '//Other module info'
    src += '-1, module_methods, NULL, NULL, NULL, NULL'
    src.unindent()
    src += '};'
    src += ''
    #Module initializer
    src += '//Module initializer'
    src += 'PyMODINIT_FUNC PyInit_%s() { return PyModule_Create(&module); }'%(module_name)
    src += ''
    #Save code to file
    file_name = Compiler.get_python_file(k)
    with open(file_name, 'w') as file:
      file.write(src.get_code())
    #print('Saved to file: %s'%(file_name))

  #Generates the Java API
  def compile_java(k, options):
    type = options.type
    args = k.get_arguments()
    src = Formatter()
    src.section('VecPy generated entry point: Java')
    #Includes
    src += '//Includes'
    src += '#include <jni.h>'
    src += ''
    #Wrapper for the core function
    src += '//Wrapper for the core function'
    arg_str = ', '.join('jobject buf_%s'%(arg.name) for arg in args)
    src += 'extern "C" JNIEXPORT jboolean JNICALL Java_%s_%s(JNIEnv* env, jclass cls, %s) {'%('VecPy', k.name, arg_str)
    src.indent()
    buffer_type = 'FloatBuffer'
    src += '//Make sure the buffers are directly allocated'
    src += 'jclass %s = env->FindClass("java/nio/%s");'%(buffer_type, buffer_type)
    src += 'jmethodID isDirect = env->GetMethodID(%s, "isDirect", "()Z");'%(buffer_type)
    for arg in args:
      src += 'if(!env->CallBooleanMethod(buf_%s, isDirect)) {'%(arg.name)
      src.indent()
      src += 'printf("Buffer not direct (%s)\\n");'%(arg.name)
      src += 'return false;'
      src.unindent()
      src += '}'
    src += '//Number of elements to process'
    src += 'jlong N = env->GetDirectBufferCapacity(buf_%s);'%(args[0].name)
    src += 'if(N == -1) {'
    src.indent()
    src += 'printf("JVM doesn\'t support direct buffers\\n");'
    src += 'return false;'
    src.unindent()
    src += '}'
    src += '//Check length for all buffers'
    for arg in args:
      src += 'if(env->GetDirectBufferCapacity(buf_%s) != N) { '%(arg.name)
      src.indent()
      src += 'printf("Java buffer sizes don\'t match (%s)\\n");'%(arg.name)
      src += 'return false;'
      src.unindent()
      src += '}'
    src += '//Extract input arrays from buffers'
    src += 'KernelArgs args;'
    for arg in args:
      src += 'args.%s = (%s*)env->GetDirectBufferAddress(buf_%s);'%(arg.name, type, arg.name)
    src += 'args.N = N;'
    for arg in args:
      src += 'if(args.%s == NULL) {'%(arg.name)
      src.indent()
      src += 'printf("Error retrieving Java buffer (%s)\\n");'%(arg.name)
      src += 'return false;'
      src.unindent()
      src += '}'
    src += '//Run the kernel'
    src += 'return run(&args);'
    src.unindent()
    src += '}'
    src += ''
    #Save code to file
    file_name = Compiler.get_java_file(k)
    with open(file_name, 'w') as file:
      file.write(src.get_code())
    #print('Saved to file: %s'%(file_name))

  #Generates the kernel
  def compile_kernel(k, options):
    src = Formatter()
    src.section('VecPy generated kernel: %s'%(k.name))
    #The KernelArgs struct
    src += '//Kernel arguments'
    src += 'struct KernelArgs {'
    src.indent()
    for arg in k.get_arguments():
      src += '%s* %s;'%(options.type, arg.name)
    src += 'unsigned int N;'
    src.unindent()
    src += '};'
    src += ''
    #Generate an architecture-specific kernel
    src += Compiler_Generic.compile_kernel(k, options)
    if Architecture.is_intel(options.arch):
      src += Compiler_Intel.compile_kernel(k, options)
    elif not Architecture.is_generic(options.arch):
      raise Exception('Target architecture not implemented (%s)'%(options.arch['name']))
    #Save code to file
    file_name = Compiler.get_kernel_file(k)
    with open(file_name, 'w') as file:
      file.write(src.get_code())
    #print('Saved to file: %s'%(file_name))

  #Compiles the module
  def build(k, build_flags):
    src = Formatter()
    #Generate the build script
    src += 'NAME=VecPy_%s.so'%(k.name)
    src += 'rm -f $NAME'
    src += 'g++ -O3 -fPIC -shared %s -o $NAME %s'%(' '.join(build_flags), Compiler.get_core_file(k))
    src += 'nm $NAME | grep " T "'
    #Save code to file
    file_name = 'build.sh'
    with open(file_name, 'w') as file:
      file.write(src.get_code())
    #print('Saved to file: %s'%(file_name))
    #Run the build script
    subprocess.call(['chmod', '+x', file_name])
    subprocess.check_call(['./' + file_name], shell=True)

  #Generates all files and compiles the module
  def compile(kernel, options):
    #Sanity checks
    if options.arch is None:
      raise Exception('No architecture specified')
    if options.bindings is None or len(options.bindings) == 0:
      raise Exception('No language bindings specified')
    #Auto-detect number of cores
    if options.threads is None or options.threads < 1:
      try:
        import multiprocessing
        options.threads = multiprocessing.cpu_count()
      except(ImportError, NotImplementedError):
        options.threads = 1
      print('Detected %s core(s)'%(options.threads))
    else:
      print('Using %s thread(s)'%(options.threads))
    #Show options
    options.show()
    #Generate the kernel
    Compiler.compile_kernel(kernel, options)
    #Generate API for each language
    include_files = []
    build_flags = [options.arch['flag']]
    if Binding.all in options.bindings or Binding.cpp in options.bindings:
      Compiler.compile_cpp(kernel, options)
      include_files.append(Compiler.get_cpp_file(kernel))
    if Binding.all in options.bindings or Binding.python in options.bindings:
      Compiler.compile_python(kernel, options)
      include_files.append(Compiler.get_python_file(kernel))
      build_flags.append('-lpython3.3m')
      build_flags.append('-I/usr/include/python3.3m/')
    if Binding.all in options.bindings or Binding.java in options.bindings:
      Compiler.compile_java(kernel, options)
      include_files.append(Compiler.get_java_file(kernel))
      build_flags.append('-I/usr/java/latest/include/')
      build_flags.append('-I/usr/java/latest/include/linux/')
    #Generate the core
    Compiler.compile_core(kernel, options, include_files)
    #Compile the module
    Compiler.build(kernel, build_flags)

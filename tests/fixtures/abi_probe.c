/* SPDX-License-Identifier: Apache-2.0 */
/* Software-only probe of copied headers. It defines/calls no model entry point. */
#include "IEEE_Cigre_DLLInterface.h"
#include <float.h>
#include <limits.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>

#if defined(_MSC_VER)
#define ALIGNOF(type) __alignof(type)
#else
#define ALIGNOF(type) __alignof__(type)
#endif

typedef struct { uint8_t field_0; double field_1[3]; int16_t field_2[2]; float field_3; } MixedInputs;
typedef struct { float field_0[2]; uint8_t field_1; double field_2; } MixedOutputs;
typedef struct { float field_0; double field_1; int32_t field_2; uint8_t field_3; const char *field_4; }
    MixedParameters;

static int first_field;
static int first_record = 1;
static void begin_record(const char *name, size_t size, size_t alignment) {
    printf("%s\"%s\":{\"size\":%zu,\"alignment\":%zu,\"fields\":{",
           first_record ? "" : ",", name, size, alignment);
    first_record = 0;
    first_field = 1;
}
static void field(const char *name, size_t offset, size_t size, size_t alignment) {
    printf("%s\"%s\":{\"offset\":%zu,\"size\":%zu,\"alignment\":%zu}",
           first_field ? "" : ",", name, offset, size, alignment);
    first_field = 0;
}
#define BEGIN(label, type) begin_record(label, sizeof(type), ALIGNOF(type))
#define FIELD(type, member, member_type) \
    field(#member, offsetof(type, member), sizeof(((type *)0)->member), ALIGNOF(member_type))
#define END() printf("}}")

static void scalar(const char *name, size_t size, size_t alignment, const char *signedness) {
    printf("%s\"%s\":{\"size\":%zu,\"alignment\":%zu,\"signedness\":\"%s\"}",
           first_record ? "" : ",", name, size, alignment, signedness);
    first_record = 0;
}
#define SCALAR(label, type, signedness) scalar(label, sizeof(type), ALIGNOF(type), signedness)

int main(void) {
    unsigned int one = 1;
    unsigned char bytes[sizeof(one)];
    char minus_one = (char)-1;
    memcpy(bytes, &one, sizeof(one));
    printf("{\"schema\":\"inverter-native-abi-observation/1\","
           "\"scope\":\"host-header-software-probe\",\"producer_library_attestation\":false,"
           "\"endianness\":\"%s\",\"char_bits\":%d,"
           "\"float_representation\":{\"radix\":%d,\"float_mantissa_bits\":%d,"
           "\"double_mantissa_bits\":%d},",
           bytes[0] == 1 ? "little" : bytes[sizeof(one) - 1] == 1 ? "big" : "mixed",
           CHAR_BIT, FLT_RADIX, FLT_MANT_DIG, DBL_MANT_DIG);
#if defined(__clang__)
    printf("\"compiler_macros\":{\"family\":\"clang\",\"major\":%d,\"minor\":%d,\"patch\":%d},",
           __clang_major__, __clang_minor__, __clang_patchlevel__);
#elif defined(_MSC_VER)
    printf("\"compiler_macros\":{\"family\":\"msvc\",\"version\":%d},", _MSC_VER);
#elif defined(__GNUC__)
    printf("\"compiler_macros\":{\"family\":\"gcc\",\"major\":%d,\"minor\":%d,\"patch\":%d},",
           __GNUC__, __GNUC_MINOR__, __GNUC_PATCHLEVEL__);
#else
    printf("\"compiler_macros\":{\"family\":\"unknown\"},");
#endif
    printf("\"scalars\":{");
    SCALAR("char", char, minus_one < 0 ? "signed" : "unsigned");
    SCALAR("int8_t", int8_t, "signed"); SCALAR("uint8_t", uint8_t, "unsigned");
    SCALAR("int16_t", int16_t, "signed"); SCALAR("uint16_t", uint16_t, "unsigned");
    SCALAR("int32_t", int32_t, "signed"); SCALAR("uint32_t", uint32_t, "unsigned");
    SCALAR("int", int, "signed"); SCALAR("long", long, "signed");
    SCALAR("float", float, "not-applicable"); SCALAR("double", double, "not-applicable");
    SCALAR("pointer", void *, "not-applicable");
    printf("},\"enums\":{"); first_record = 1;
    SCALAR("DataType", IEEE_Cigre_DLLInterface_DataType_Enum,
           (IEEE_Cigre_DLLInterface_DataType_Enum)-1 < 0 ? "signed" : "unsigned");
    SCALAR("ReturnValue", IEEE_Cigre_DLLInterface_Return_Value,
           (IEEE_Cigre_DLLInterface_Return_Value)-1 < 0 ? "signed" : "unsigned");
    printf("},\"datatype_ids\":[%d,%d,%d,%d,%d,%d,%d,%d,%d,%d],\"aggregates\":{",
           IEEE_Cigre_DLLInterface_DataType_char_T, IEEE_Cigre_DLLInterface_DataType_int8_T,
           IEEE_Cigre_DLLInterface_DataType_uint8_T, IEEE_Cigre_DLLInterface_DataType_int16_T,
           IEEE_Cigre_DLLInterface_DataType_uint16_T, IEEE_Cigre_DLLInterface_DataType_int32_T,
           IEEE_Cigre_DLLInterface_DataType_uint32_T, IEEE_Cigre_DLLInterface_DataType_real32_T,
           IEEE_Cigre_DLLInterface_DataType_real64_T, IEEE_Cigre_DLLInterface_DataType_c_string_T);
    first_record = 1;
    BEGIN("Signal", IEEE_Cigre_DLLInterface_Signal);
    FIELD(IEEE_Cigre_DLLInterface_Signal, Name, const char *);
    FIELD(IEEE_Cigre_DLLInterface_Signal, Description, const char *);
    FIELD(IEEE_Cigre_DLLInterface_Signal, Unit, const char *);
    FIELD(IEEE_Cigre_DLLInterface_Signal, DataType, int);
    FIELD(IEEE_Cigre_DLLInterface_Signal, Width, int); END();
    BEGIN("DefaultValue", IEEE_Cigre_DLLInterface_DefaultValue);
    FIELD(IEEE_Cigre_DLLInterface_DefaultValue, Char_Val, char);
    FIELD(IEEE_Cigre_DLLInterface_DefaultValue, Char_Ptr, const char *);
    FIELD(IEEE_Cigre_DLLInterface_DefaultValue, Int8_Val, int8_t);
    FIELD(IEEE_Cigre_DLLInterface_DefaultValue, Uint8_Val, uint8_t);
    FIELD(IEEE_Cigre_DLLInterface_DefaultValue, Int16_Val, int16_t);
    FIELD(IEEE_Cigre_DLLInterface_DefaultValue, Uint16_Val, uint16_t);
    FIELD(IEEE_Cigre_DLLInterface_DefaultValue, Int32_Val, int32_t);
    FIELD(IEEE_Cigre_DLLInterface_DefaultValue, Uint32_Val, uint32_t);
    FIELD(IEEE_Cigre_DLLInterface_DefaultValue, Real32_Val, float);
    FIELD(IEEE_Cigre_DLLInterface_DefaultValue, Real64_Val, double); END();
    BEGIN("MinMaxValue", IEEE_Cigre_DLLInterface_MinMaxValue);
    FIELD(IEEE_Cigre_DLLInterface_MinMaxValue, Char_Val, char);
    FIELD(IEEE_Cigre_DLLInterface_MinMaxValue, Int8_Val, int8_t);
    FIELD(IEEE_Cigre_DLLInterface_MinMaxValue, Uint8_Val, uint8_t);
    FIELD(IEEE_Cigre_DLLInterface_MinMaxValue, Int16_Val, int16_t);
    FIELD(IEEE_Cigre_DLLInterface_MinMaxValue, Uint16_Val, uint16_t);
    FIELD(IEEE_Cigre_DLLInterface_MinMaxValue, Int32_Val, int32_t);
    FIELD(IEEE_Cigre_DLLInterface_MinMaxValue, Uint32_Val, uint32_t);
    FIELD(IEEE_Cigre_DLLInterface_MinMaxValue, Real32_Val, float);
    FIELD(IEEE_Cigre_DLLInterface_MinMaxValue, Real64_Val, double); END();
    BEGIN("Parameter", IEEE_Cigre_DLLInterface_Parameter);
    FIELD(IEEE_Cigre_DLLInterface_Parameter, Name, const char *);
    FIELD(IEEE_Cigre_DLLInterface_Parameter, GroupName, const char *);
    FIELD(IEEE_Cigre_DLLInterface_Parameter, Description, const char *);
    FIELD(IEEE_Cigre_DLLInterface_Parameter, Unit, const char *);
    FIELD(IEEE_Cigre_DLLInterface_Parameter, DataType, int);
    FIELD(IEEE_Cigre_DLLInterface_Parameter, FixedValue, int);
    FIELD(IEEE_Cigre_DLLInterface_Parameter, DefaultValue, IEEE_Cigre_DLLInterface_DefaultValue);
    FIELD(IEEE_Cigre_DLLInterface_Parameter, MinValue, IEEE_Cigre_DLLInterface_MinMaxValue);
    FIELD(IEEE_Cigre_DLLInterface_Parameter, MaxValue, IEEE_Cigre_DLLInterface_MinMaxValue); END();
    BEGIN("ModelInfo", IEEE_Cigre_DLLInterface_Model_Info);
    FIELD(IEEE_Cigre_DLLInterface_Model_Info, DLLInterfaceVersion, uint8_t);
    FIELD(IEEE_Cigre_DLLInterface_Model_Info, ModelName, const char *);
    FIELD(IEEE_Cigre_DLLInterface_Model_Info, ModelVersion, const char *);
    FIELD(IEEE_Cigre_DLLInterface_Model_Info, ModelDescription, const char *);
    FIELD(IEEE_Cigre_DLLInterface_Model_Info, GeneralInformation, const char *);
    FIELD(IEEE_Cigre_DLLInterface_Model_Info, ModelCreated, const char *);
    FIELD(IEEE_Cigre_DLLInterface_Model_Info, ModelCreator, const char *);
    FIELD(IEEE_Cigre_DLLInterface_Model_Info, ModelLastModifiedDate, const char *);
    FIELD(IEEE_Cigre_DLLInterface_Model_Info, ModelLastModifiedBy, const char *);
    FIELD(IEEE_Cigre_DLLInterface_Model_Info, ModelModifiedComment, const char *);
    FIELD(IEEE_Cigre_DLLInterface_Model_Info, ModelModifiedHistory, const char *);
    FIELD(IEEE_Cigre_DLLInterface_Model_Info, FixedStepBaseSampleTime, double);
    FIELD(IEEE_Cigre_DLLInterface_Model_Info, EMT_RMS_Mode, uint8_t);
    FIELD(IEEE_Cigre_DLLInterface_Model_Info, NumInputPorts, int);
    FIELD(IEEE_Cigre_DLLInterface_Model_Info, InputPortsInfo, void *);
    FIELD(IEEE_Cigre_DLLInterface_Model_Info, NumOutputPorts, int);
    FIELD(IEEE_Cigre_DLLInterface_Model_Info, OutputPortsInfo, void *);
    FIELD(IEEE_Cigre_DLLInterface_Model_Info, NumParameters, int);
    FIELD(IEEE_Cigre_DLLInterface_Model_Info, ParametersInfo, void *);
    FIELD(IEEE_Cigre_DLLInterface_Model_Info, NumIntStates, int);
    FIELD(IEEE_Cigre_DLLInterface_Model_Info, NumFloatStates, int);
    FIELD(IEEE_Cigre_DLLInterface_Model_Info, NumDoubleStates, int); END();
    BEGIN("Instance", IEEE_Cigre_DLLInterface_Instance);
    FIELD(IEEE_Cigre_DLLInterface_Instance, ExternalInputs, void *);
    FIELD(IEEE_Cigre_DLLInterface_Instance, ExternalOutputs, void *);
    FIELD(IEEE_Cigre_DLLInterface_Instance, Parameters, void *);
    FIELD(IEEE_Cigre_DLLInterface_Instance, Time, double);
    FIELD(IEEE_Cigre_DLLInterface_Instance, SimTool_EMT_RMS_Mode, uint8_t);
    FIELD(IEEE_Cigre_DLLInterface_Instance, LastErrorMessage, const char *);
    FIELD(IEEE_Cigre_DLLInterface_Instance, LastGeneralMessage, const char *);
    FIELD(IEEE_Cigre_DLLInterface_Instance, IntStates, void *);
    FIELD(IEEE_Cigre_DLLInterface_Instance, FloatStates, void *);
    FIELD(IEEE_Cigre_DLLInterface_Instance, DoubleStates, void *); END();
    BEGIN("MixedInputs", MixedInputs);
    FIELD(MixedInputs, field_0, uint8_t); FIELD(MixedInputs, field_1, double);
    FIELD(MixedInputs, field_2, int16_t); FIELD(MixedInputs, field_3, float); END();
    BEGIN("MixedOutputs", MixedOutputs);
    FIELD(MixedOutputs, field_0, float); FIELD(MixedOutputs, field_1, uint8_t);
    FIELD(MixedOutputs, field_2, double); END();
    BEGIN("MixedParameters", MixedParameters);
    FIELD(MixedParameters, field_0, float); FIELD(MixedParameters, field_1, double);
    FIELD(MixedParameters, field_2, int32_t); FIELD(MixedParameters, field_3, uint8_t);
    FIELD(MixedParameters, field_4, const char *); END();
    printf("}}\n");
    return 0;
}
